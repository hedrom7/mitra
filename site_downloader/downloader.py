"""Core site downloading logic using Playwright."""
from __future__ import annotations

import asyncio
import json
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional, Set, Tuple
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from playwright.async_api import Browser, BrowserContext, Page, async_playwright

from .path_utils import LocalPathMapping, make_relative, normalize_url, url_to_local_path

LogCallback = Callable[[str], None]
ProgressCallback = Callable[[int, int, int], None]

CSS_URL_RE = re.compile(r"""url\(\s*["']?\s*([^"')\s]+)\s*["']?\s*\)""")
CSS_IMPORT_RE = re.compile(r"""@import\s+["']([^"']+)["']""")

# External font CDN hosts we want to download and serve locally
FONT_CDN_HOSTS: frozenset = frozenset({
    "fonts.googleapis.com",
    "fonts.gstatic.com",
})


@dataclass
class DownloadOptions:
    max_depth: int = 1
    scroll_steps: int = 6
    scroll_pause_ms: int = 400
    same_domain_only: bool = True
    headless: bool = True
    wait_after_interactions_ms: int = 1000
    max_concurrent: int = 3
    max_file_size_mb: float = 50.0
    rate_limit_ms: int = 200
    max_retries: int = 3
    resume: bool = True


@dataclass
class DownloadStats:
    pages_found: int = 0
    pages_completed: int = 0
    assets_saved: int = 0
    assets_skipped: int = 0
    bytes_downloaded: int = 0
    errors: int = 0


@dataclass
class DownloadContext:
    base_url: str
    destination: Path
    options: DownloadOptions
    log: LogCallback
    on_progress: Optional[ProgressCallback] = None

    visited_pages: Set[str] = field(default_factory=set)
    queued_pages: asyncio.Queue[Tuple[str, int]] = field(default_factory=asyncio.Queue)
    # URL → local path mapping (for link rewriting)
    stored_assets: dict[str, Path] = field(default_factory=dict)
    # URLs that have actually been written to disk
    saved_urls: Set[str] = field(default_factory=set)
    stop_event: threading.Event = field(default_factory=threading.Event)
    stats: DownloadStats = field(default_factory=DownloadStats)

    def __post_init__(self) -> None:
        self.base_url = normalize_url(self.base_url)
        self.destination = self.destination.resolve()
        self.destination.mkdir(parents=True, exist_ok=True)

    @property
    def base_host(self) -> str:
        return urlparse(self.base_url).netloc

    @property
    def is_stopped(self) -> bool:
        return self.stop_event.is_set()

    @staticmethod
    def _bare_host(netloc: str) -> str:
        """Strip 'www.' and optional port for domain comparison."""
        host = netloc.split(":")[0].lower()
        if host.startswith("www."):
            host = host[4:]
        return host

    def is_internal(self, url: str) -> bool:
        parsed = urlparse(url)
        if not parsed.scheme.startswith("http"):
            return False
        if not self.options.same_domain_only:
            return True
        return self._bare_host(parsed.netloc) == self._bare_host(self.base_host)

    def is_saveable(self, url: str) -> bool:
        """True for internal URLs AND known font CDN hosts (fonts.googleapis.com etc.)."""
        if self.is_internal(url):
            return True
        parsed = urlparse(url)
        host = parsed.netloc.split(":")[0].lower()
        return host in FONT_CDN_HOSTS

    def enqueue(self, url: str, depth: int) -> None:
        normalized = normalize_url(url)
        if normalized in self.visited_pages:
            return
        if depth > self.options.max_depth:
            return
        self.stats.pages_found += 1
        self.queued_pages.put_nowait((normalized, depth))

    def notify_progress(self) -> None:
        if self.on_progress:
            self.on_progress(
                self.stats.pages_completed,
                self.stats.pages_found,
                self.stats.assets_saved,
            )


class SiteDownloader:
    def __init__(self, context: DownloadContext) -> None:
        self.context = context
        self._browser: Optional[Browser] = None
        self._semaphore = asyncio.Semaphore(context.options.max_concurrent)
        self._asset_lock = asyncio.Lock()

    async def run(self) -> None:
        ctx = self.context
        ctx.log("İndirici başlatılıyor…")

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=ctx.options.headless)
            self._browser = browser
            browser_ctx = await browser.new_context()

            ctx.enqueue(ctx.base_url, 0)
            active: set[asyncio.Task] = set()

            while True:
                if ctx.is_stopped:
                    ctx.log("Durduruldu.")
                    break

                try:
                    url, depth = await asyncio.wait_for(
                        ctx.queued_pages.get(), timeout=3.0
                    )
                except asyncio.TimeoutError:
                    if not active:
                        break
                    continue

                if url in ctx.visited_pages:
                    continue
                ctx.visited_pages.add(url)

                await self._semaphore.acquire()

                if ctx.options.rate_limit_ms > 0:
                    await asyncio.sleep(ctx.options.rate_limit_ms / 1000.0)

                task = asyncio.create_task(self._safe_process(browser_ctx, url, depth))
                active.add(task)
                task.add_done_callback(
                    lambda t: (active.discard(t), self._semaphore.release())
                )

            if active:
                await asyncio.gather(*active, return_exceptions=True)

            # Download any assets referenced in CSS/HTML but not yet on disk
            if not ctx.is_stopped:
                await self._download_missing_assets(browser_ctx)

            await browser_ctx.close()
            await browser.close()
            self._browser = None

        s = ctx.stats
        ctx.log(
            f"Tamamlandı: {s.pages_completed} sayfa, "
            f"{s.assets_saved} asset, {s.errors} hata"
        )

    async def stop(self) -> None:
        self.context.stop_event.set()
        if self._browser:
            try:
                await self._browser.close()
            except Exception:
                pass

    # -- page processing --------------------------------------------------

    async def _safe_process(
        self, browser_ctx: BrowserContext, url: str, depth: int
    ) -> None:
        try:
            await self._process_page(browser_ctx, url, depth)
        except Exception as exc:
            self.context.stats.errors += 1
            self.context.log(f"Hata ({url}): {exc}")

    async def _process_page(
        self, browser_ctx: BrowserContext, url: str, depth: int
    ) -> None:
        ctx = self.context
        if ctx.is_stopped:
            return

        html_mapping = url_to_local_path(ctx.destination, url, content_type="text/html")

        # Resume: skip already downloaded pages
        if ctx.options.resume and html_mapping.full_path.exists():
            ctx.log(f"Atlanıyor (mevcut): {url}")
            ctx.saved_urls.add(url)
            ctx.stats.pages_completed += 1
            ctx.stats.assets_skipped += 1
            ctx.notify_progress()
            return

        ctx.log(f"İndiriliyor: {url} (derinlik {depth})")

        page = await browser_ctx.new_page()
        captured: list = []
        page.on("response", lambda r: captured.append(r))

        # Retry loop
        loaded = False
        for attempt in range(1, ctx.options.max_retries + 1):
            if ctx.is_stopped:
                await page.close()
                return
            try:
                await page.goto(url, wait_until="load", timeout=60_000)
                loaded = True
                break
            except Exception as exc:
                if attempt < ctx.options.max_retries:
                    ctx.log(
                        f"Tekrar deneniyor ({attempt}/{ctx.options.max_retries}): {url}"
                    )
                    await asyncio.sleep(1)
                else:
                    ctx.log(f"Yüklenemedi: {url} — {exc}")
                    ctx.stats.errors += 1
                    await page.close()
                    return

        if not loaded:
            await page.close()
            return

        # Follow redirect: use the final URL after navigation
        final_url = normalize_url(page.url)
        if final_url != url and ctx.is_internal(final_url):
            if final_url in ctx.visited_pages:
                # Already downloaded via redirect destination — skip duplicate
                await page.close()
                return
            ctx.log(f"Yönlendirme: {url} → {final_url}")
            ctx.visited_pages.add(final_url)
            html_mapping = url_to_local_path(
                ctx.destination, final_url, content_type="text/html"
            )
            url = final_url
            # Resume check for the final (redirected) URL
            if ctx.options.resume and html_mapping.full_path.exists():
                ctx.log(f"Atlanıyor (mevcut): {url}")
                ctx.saved_urls.add(url)
                ctx.stats.pages_completed += 1
                ctx.stats.assets_skipped += 1
                ctx.notify_progress()
                await page.close()
                return

        # Scroll for lazy content
        await self._scroll(page)
        await page.wait_for_timeout(ctx.options.wait_after_interactions_ms)

        # Save network assets while page is still alive
        for resp in captured:
            await self._save_asset(resp)

        # Scroll back to top so header/nav returns to its default state.
        await page.evaluate("window.scrollTo(0, 0)")
        await page.wait_for_timeout(500)

        html = await page.content()
        await page.close()

        # Save & rewrite HTML
        html_mapping.directory.mkdir(parents=True, exist_ok=True)
        rewritten, links = self._rewrite_html(html, url, html_mapping)
        html_mapping.full_path.write_text(rewritten, encoding="utf-8")

        ctx.stored_assets[url] = html_mapping.full_path
        ctx.saved_urls.add(url)
        ctx.stats.pages_completed += 1
        ctx.stats.bytes_downloaded += len(rewritten.encode("utf-8"))
        ctx.notify_progress()
        ctx.log(f"Kaydedildi: {url}")

        for link in links:
            if link not in ctx.visited_pages:
                ctx.enqueue(link, depth + 1)

    async def _scroll(self, page: Page) -> None:
        for _ in range(self.context.options.scroll_steps):
            if self.context.is_stopped:
                return
            await page.mouse.wheel(0, 1200)
            await page.wait_for_timeout(self.context.options.scroll_pause_ms)

    # -- asset saving -----------------------------------------------------

    async def _save_asset(self, response) -> None:
        url = normalize_url(response.url)
        ctx = self.context

        if not ctx.is_saveable(url):
            return
        if response.request.resource_type == "document":
            return
        # Only skip if actually saved to disk (not just planned in stored_assets)
        if url in ctx.saved_urls:
            return

        # File size guard (header check)
        max_bytes = ctx.options.max_file_size_mb * 1024 * 1024
        content_length = response.headers.get("content-length")
        if content_length and int(content_length) > max_bytes:
            ctx.log(
                f"Atlanıyor (büyük: {int(content_length) / 1024 / 1024:.1f} MB): {url}"
            )
            ctx.stats.assets_skipped += 1
            return

        try:
            body = await response.body()
        except Exception:
            return

        # File size guard (body check)
        if len(body) > max_bytes:
            ctx.log(f"Atlanıyor (büyük: {len(body) / 1024 / 1024:.1f} MB): {url}")
            ctx.stats.assets_skipped += 1
            return

        content_type = response.headers.get("content-type", "")
        mapping = url_to_local_path(ctx.destination, url, content_type=content_type)

        async with self._asset_lock:
            if url in ctx.saved_urls:
                return

            # Resume: skip existing files
            if ctx.options.resume and mapping.full_path.exists():
                ctx.stored_assets[url] = mapping.full_path
                ctx.saved_urls.add(url)
                ctx.stats.assets_skipped += 1
                return

            mapping.directory.mkdir(parents=True, exist_ok=True)
            data = body

            if "text/css" in content_type or mapping.full_path.suffix == ".css":
                try:
                    data = self._rewrite_css(
                        body.decode("utf-8"), url, mapping
                    ).encode("utf-8")
                except Exception:
                    pass
            elif "application/json" in content_type:
                try:
                    data = json.dumps(
                        json.loads(body.decode("utf-8")), indent=2
                    ).encode("utf-8")
                except Exception:
                    pass

            mapping.full_path.write_bytes(data)
            ctx.stored_assets[url] = mapping.full_path
            ctx.saved_urls.add(url)
            ctx.stats.assets_saved += 1
            ctx.stats.bytes_downloaded += len(data)
            ctx.notify_progress()

    # -- missing asset download -------------------------------------------

    async def _download_missing_assets(self, browser_ctx: BrowserContext) -> None:
        """Download assets referenced in CSS/HTML but not yet saved to disk."""
        ctx = self.context
        missing = {
            url: path
            for url, path in ctx.stored_assets.items()
            if url not in ctx.saved_urls
            and not path.exists()
            and not self._is_page_url(url)
            and ctx.is_saveable(url)
        }

        if not missing:
            return

        ctx.log(f"{len(missing)} eksik asset indiriliyor (fontlar, CSS referansları)…")

        for url, local_path in missing.items():
            if ctx.is_stopped:
                break
            try:
                resp = await browser_ctx.request.get(url)
                if resp.ok:
                    body = await resp.body()
                    max_bytes = ctx.options.max_file_size_mb * 1024 * 1024
                    if len(body) > max_bytes:
                        continue
                    local_path.parent.mkdir(parents=True, exist_ok=True)
                    local_path.write_bytes(body)
                    ctx.saved_urls.add(url)
                    ctx.stats.assets_saved += 1
                    ctx.stats.bytes_downloaded += len(body)
                    ctx.notify_progress()
            except Exception as exc:
                ctx.stats.errors += 1

        ctx.log("Eksik asset indirme tamamlandı.")

    # -- HTML rewriting ---------------------------------------------------

    def _rewrite_html(
        self,
        html: str,
        page_url: str,
        html_mapping: LocalPathMapping,
    ) -> Tuple[str, Set[str]]:
        soup = BeautifulSoup(html, "html.parser")
        links: Set[str] = set()

        def rewrite(tag, attr, collect=False):
            val = tag.get(attr)
            if not val:
                return
            new, norm = self._rewrite_link(val, page_url, html_mapping)
            if new is not None:
                tag[attr] = new
            if collect and norm and self._is_page_url(norm):
                links.add(norm)

        # Standard attributes
        for t in soup.find_all(src=True):
            rewrite(t, "src")
        for t in soup.find_all("a", href=True):
            rewrite(t, "href", collect=True)
        for t in soup.find_all("link", href=True):
            rewrite(t, "href")
        for t in soup.find_all(poster=True):
            rewrite(t, "poster")
        for t in soup.find_all("source", src=True):
            rewrite(t, "src")

        # Lazy-load / data attributes
        for attr in ("data-src", "data-bg", "data-lazy-src", "data-original"):
            for t in soup.find_all(attrs={attr: True}):
                rewrite(t, attr)

        # srcset and data-srcset
        for attr in ("srcset", "data-srcset"):
            for t in soup.find_all(attrs={attr: True}):
                srcset = t.get(attr, "")
                parts = []
                for chunk in srcset.split(","):
                    chunk = chunk.strip()
                    if not chunk:
                        continue
                    pieces = chunk.split()
                    new, norm = self._rewrite_link(pieces[0], page_url, html_mapping)
                    if new is None:
                        parts.append(chunk)
                    else:
                        if norm and self._is_page_url(norm):
                            links.add(norm)
                        parts.append(" ".join([new] + pieces[1:]))
                t[attr] = ", ".join(parts)

        # Inline style attributes
        for t in soup.find_all(style=True):
            t["style"] = self._rewrite_css(t["style"], page_url, html_mapping)

        # <style> blocks
        for t in soup.find_all("style"):
            if t.string:
                t.string = self._rewrite_css(t.string, page_url, html_mapping)

        # Clean sticky/fixed header state injected by JS during scroll.
        self._clean_sticky_state(soup)

        # Clean SmartMenus / nav-JS injected DOM state so it re-initialises
        # cleanly when the offline page is opened (prevents doubled arrows).
        self._clean_nav_js_state(soup)

        # Use str(soup) instead of prettify() to preserve original formatting
        return str(soup), links

    @staticmethod
    def _clean_sticky_state(soup: BeautifulSoup) -> None:
        """Remove scroll-injected sticky header state from the DOM.

        Elementor clones sticky elements: the original is hidden
        (visibility:hidden) and a clone gets position:fixed.  We must
        remove the clone first, then restore the original.
        """
        STICKY_STYLE_PROPS = {
            "position", "width", "margin-top", "margin-bottom",
            "top", "inset", "transform", "visibility",
            "transition", "animation",
        }

        STICKY_CLASSES = {
            "elementor-sticky--active", "elementor-sticky--effects",
            "sticky-active", "is-stuck", "is-fixed", "nav-fixed",
            "header-fixed", "fixed-header", "stuck",
        }

        # 1. Remove spacer/placeholder divs that sticky JS inserts
        for tag in list(soup.find_all(
            class_=re.compile(r"elementor-sticky--spacer|sticky-spacer|header-placeholder")
        )):
            tag.decompose()

        # 2. Process Elementor sticky elements in one pass:
        #    - Remove clones (duplicate element-id)
        #    - Clean inline styles on the original
        seen_ids: set = set()
        to_remove = []
        to_clean = []

        for tag in soup.find_all(attrs={"data-settings": True}):
            settings = tag.get("data-settings", "")
            if '"sticky"' not in settings:
                continue
            el_id = None
            for cls in tag.get("class", []):
                if cls.startswith("elementor-element-") and cls != "elementor-element":
                    el_id = cls
                    break
            if el_id and el_id in seen_ids:
                to_remove.append(tag)
            else:
                if el_id:
                    seen_ids.add(el_id)
                to_clean.append(tag)

        for tag in to_remove:
            tag.decompose()

        for tag in to_clean:
            style = tag.get("style", "")
            if not style:
                continue
            kept = []
            for part in style.split(";"):
                part = part.strip()
                if not part:
                    continue
                prop = part.split(":")[0].strip().lower()
                if prop not in STICKY_STYLE_PROPS:
                    kept.append(part)
            if kept:
                tag["style"] = "; ".join(kept) + ";"
            elif "style" in tag.attrs:
                del tag["style"]

        # 3. Remove sticky-state classes
        for cls in STICKY_CLASSES:
            for tag in soup.find_all(class_=cls):
                tag["class"] = [c for c in tag.get("class", []) if c not in STICKY_CLASSES]

    @staticmethod
    def _clean_nav_js_state(soup: BeautifulSoup) -> None:
        """Remove SmartMenus / Elementor nav-JS DOM injections.

        When Playwright captures the page, the nav JS has already run and
        injected sub-arrow spans, SmartMenus IDs, and ARIA attributes.
        Opening the offline HTML re-runs that JS, which would inject them a
        *second* time (doubling dropdown arrows and breaking the layout).
        We strip those injections so JS starts from a clean slate.
        """
        SM_ID_RE = re.compile(r"^sm-\d+")

        for nav in soup.find_all("ul", attrs={"data-smartmenus-id": True}):
            # Remove SmartMenus runtime data attribute from the <ul>
            del nav["data-smartmenus-id"]

        for a in soup.find_all("a"):
            # Remove SmartMenus-generated IDs (sm-XXXXXXXXX-N)
            a_id = a.get("id", "")
            if SM_ID_RE.match(a_id):
                del a["id"]

            # Remove SmartMenus ARIA attributes added at runtime
            for attr in ("aria-controls", "aria-expanded", "aria-haspopup"):
                if attr in a.attrs and SM_ID_RE.match(a.get(attr, "")):
                    del a[attr]

            # Remove "has-submenu" class added by SmartMenus
            if "has-submenu" in a.get("class", []):
                a["class"] = [c for c in a["class"] if c != "has-submenu"]

            # Remove sub-arrow <span> appended inside <a> by SmartMenus
            for span in a.find_all("span", class_="sub-arrow"):
                span.decompose()

        # Clean SmartMenus ARIA on sub-menu <ul> elements
        for ul in soup.find_all("ul", class_="sub-menu"):
            for attr in ("id", "role", "aria-expanded", "aria-hidden",
                         "aria-labelledby"):
                if attr in ul.attrs and (
                    not ul[attr] or SM_ID_RE.match(str(ul[attr]))
                ):
                    del ul[attr]

    # -- CSS rewriting ----------------------------------------------------

    def _rewrite_css(
        self, css: str, css_url: str, mapping: LocalPathMapping
    ) -> str:
        def _replace_url(m: re.Match) -> str:
            raw = m.group(1).strip()
            if raw.startswith("data:"):
                return m.group(0)
            absolute = urljoin(css_url, raw)
            norm = normalize_url(absolute)
            if not self.context.is_saveable(norm):
                return m.group(0)
            asset = url_to_local_path(self.context.destination, norm)
            self.context.stored_assets.setdefault(norm, asset.full_path)
            return f'url("{make_relative(mapping.full_path, asset.full_path)}")'

        def _replace_import(m: re.Match) -> str:
            raw = m.group(1).strip()
            if raw.startswith("data:"):
                return m.group(0)
            absolute = urljoin(css_url, raw)
            norm = normalize_url(absolute)
            if not self.context.is_saveable(norm):
                return m.group(0)
            asset = url_to_local_path(self.context.destination, norm)
            self.context.stored_assets.setdefault(norm, asset.full_path)
            return f'@import "{make_relative(mapping.full_path, asset.full_path)}"'

        css = CSS_URL_RE.sub(_replace_url, css)
        css = CSS_IMPORT_RE.sub(_replace_import, css)
        return css

    # -- link helpers -----------------------------------------------------

    @staticmethod
    def _is_page_url(url: str) -> bool:
        parsed = urlparse(url)
        suffix = Path(parsed.path).suffix.lower()
        return suffix in {
            "", ".html", ".htm", ".php", ".asp", ".aspx", ".xhtml"
        } or parsed.path.endswith("/")

    def _rewrite_link(
        self,
        value: str,
        page_url: str,
        html_mapping: LocalPathMapping,
    ) -> Tuple[Optional[str], Optional[str]]:
        value = value.strip()
        if value.startswith(("data:", "javascript:", "mailto:", "tel:", "#")):
            return None, None
        absolute = urljoin(page_url, value)
        normalized = normalize_url(absolute)
        if not self.context.is_saveable(normalized):
            return None, None
        # Prefer the path already registered by _save_asset (which knows content-type).
        # Fall back to a content-type-agnostic guess only if not yet known.
        if normalized in self.context.stored_assets:
            local_path = self.context.stored_assets[normalized]
        else:
            temp = url_to_local_path(self.context.destination, normalized)
            self.context.stored_assets.setdefault(normalized, temp.full_path)
            local_path = self.context.stored_assets[normalized]
        relative = make_relative(html_mapping.full_path, local_path)
        return relative, normalized
