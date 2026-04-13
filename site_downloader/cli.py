"""Command-line interface for the site downloader."""
from __future__ import annotations

import argparse
import asyncio
import os
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

from .downloader import DownloadContext, DownloadOptions, SiteDownloader


# ─── Playwright auto-install ─────────────────────────────────────────────────

def _ensure_browser() -> None:
    """Playwright Chromium yüklü değilse otomatik indir."""
    from playwright.sync_api import sync_playwright
    try:
        with sync_playwright() as p:
            br = p.chromium.launch(headless=True)
            br.close()
    except Exception:
        print()
        print("  Tarayıcı (Chromium) bulunamadı.")
        print("  İlk kurulum için indiriliyor (~170 MB)…")
        print()
        result = subprocess.run(
            [sys.executable, "-m", "playwright", "install", "chromium"],
        )
        if result.returncode != 0:
            print()
            print("  HATA: Tarayıcı yüklenemedi.")
            print("  Şunu çalıştırmayı deneyin:  playwright install chromium")
            sys.exit(1)
        print()


# ─── Argüman ayrıştırıcı ─────────────────────────────────────────────────────

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="mitra",
        description="Mitra — web sitelerini offline olarak indiren araç",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
örnekler:
  mitra                                        # interaktif mod
  mitra https://example.com                    # varsayılan klasöre indir
  mitra https://example.com -o ~/sites/ex      # klasör belirt
  mitra https://shop.com -o ./shop -d 3 -c 5  # 3 derinlik, 5 eş zamanlı
""",
    )
    p.add_argument(
        "url", nargs="?",
        help="İndirilecek sitenin URL'si (belirtilmezse interaktif mod açılır)",
    )
    p.add_argument(
        "-o", "--output", default=None, metavar="KLASÖR",
        help="Kayıt klasörü (varsayılan: terminali açtığın klasör)",
    )
    p.add_argument(
        "-d", "--depth", type=int, default=1, metavar="N",
        help="Maksimum tarama derinliği (varsayılan: 1)",
    )
    p.add_argument(
        "-c", "--concurrent", type=int, default=3, metavar="N",
        help="Eş zamanlı sayfa sayısı (varsayılan: 3)",
    )
    p.add_argument(
        "--scroll", type=int, default=6, metavar="N",
        help="Lazy-load için kaydırma adımı (varsayılan: 6)",
    )
    p.add_argument(
        "--max-size", type=float, default=50.0, metavar="MB",
        help="Atlanacak maksimum dosya boyutu MB (varsayılan: 50)",
    )
    p.add_argument("--no-headless", action="store_true", help="Tarayıcıyı görünür modda aç")
    p.add_argument("--no-resume", action="store_true", help="Mevcut dosyaları da yeniden indir")
    p.add_argument(
        "--rate-limit", type=int, default=200, metavar="MS",
        help="Sayfalar arası bekleme ms (varsayılan: 200)",
    )
    return p


# ─── Banner ──────────────────────────────────────────────────────────────────

def _print_banner() -> None:
    tty = hasattr(sys.stdout, "isatty") and sys.stdout.isatty()
    cyan  = "\033[96m" if tty else ""
    dim   = "\033[2m"  if tty else ""
    reset = "\033[0m"  if tty else ""

    print(f"""{cyan}
  ███╗   ███╗██╗████████╗██████╗  █████╗
  ████╗ ████║██║╚══██╔══╝██╔══██╗██╔══██╗
  ██╔████╔██║██║   ██║   ██████╔╝███████║
  ██║╚██╔╝██║██║   ██║   ██╔══██╗██╔══██║
  ██║ ╚═╝ ██║██║   ██║   ██║  ██║██║  ██║
  ╚═╝     ╚═╝╚═╝   ╚═╝   ╚═╝  ╚═╝╚═╝  ╚═╝{reset}
  {dim}Web sitelerini offline olarak indir  v0.1.0{reset}
""")


# ─── İnteraktif mod ──────────────────────────────────────────────────────────

def _read(prompt: str, default: str = "") -> str:
    """Kullanıcıdan girdi al; boş bırakılırsa default döner."""
    hint = f"[{default}] " if default else ""
    try:
        val = input(f"  {prompt}{hint}").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        sys.exit(0)
    return val if val else default


def _interactive_mode() -> argparse.Namespace:
    """Adım adım sorular sorarak kullanıcı ayarlarını topla."""
    # Tab tamamlama (macOS/Linux)
    try:
        import readline

        def _completer(text: str, state: int) -> str | None:
            expanded = os.path.expanduser(text)
            dir_part = os.path.dirname(expanded) or "."
            base = os.path.basename(expanded)
            try:
                entries = os.listdir(dir_part)
            except OSError:
                entries = []
            matches = [
                os.path.join(dir_part, e) + ("/" if os.path.isdir(os.path.join(dir_part, e)) else "")
                for e in entries if e.startswith(base)
            ]
            return matches[state] if state < len(matches) else None

        readline.set_completer(_completer)
        readline.parse_and_bind("tab: complete")
    except ImportError:
        pass

    _sep = "  " + "─" * 46

    _print_banner()

    # ── URL ──────────────────────────────────────
    while True:
        url = _read("Site URL'si     : ")
        if url:
            break
        print("  ⚠  URL boş bırakılamaz.")
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    # ── Klasör ───────────────────────────────────
    default_dest = str(Path.cwd())
    dest = os.path.expanduser(_read("Kayıt klasörü   : ", default_dest))

    # ── Derinlik ─────────────────────────────────
    depth_str = _read("Derinlik        : ", "1")
    try:
        depth = max(0, int(depth_str))
    except ValueError:
        depth = 1

    # ── Eş zamanlı ───────────────────────────────
    conc_str = _read("Eş zamanlı      : ", "3")
    try:
        concurrent = max(1, int(conc_str))
    except ValueError:
        concurrent = 3

    # ── Gelişmiş ayarlar ─────────────────────────
    print()
    adv = _read("Gelişmiş ayarlar? (e/H) : ", "H").lower()

    scroll, max_size, rate_limit, headless, resume = 6, 50.0, 200, True, True

    if adv in ("e", "evet", "y", "yes"):
        print()
        try:
            scroll = max(0, int(_read("Kaydırma adımı   : ", "6")))
        except ValueError:
            scroll = 6
        try:
            max_size = float(_read("Maks dosya (MB)  : ", "50"))
        except ValueError:
            max_size = 50.0
        try:
            rate_limit = int(_read("Bekleme (ms)     : ", "200"))
        except ValueError:
            rate_limit = 200
        hl = _read("Headless tarayıcı (E/h) : ", "E").lower()
        headless = hl not in ("h", "hayır", "n", "no")
        rs = _read("Mevcut dosyaları atla (E/h) : ", "E").lower()
        resume = rs not in ("h", "hayır", "n", "no")

    # ── Özet ─────────────────────────────────────
    print()
    print(_sep)
    print(f"  ▶  {url}")
    print(f"  📁 {dest}")
    print(f"  Derinlik: {depth}  |  Eş zamanlı: {concurrent}  |  Kaydırma: {scroll}")
    print(_sep)
    print()

    try:
        confirm = input("  Başlatmak için Enter'a basın  (q = iptal): ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        sys.exit(0)

    if confirm in ("q", "iptal", "hayır", "n"):
        print("  İptal edildi.")
        sys.exit(0)

    return argparse.Namespace(
        url=url,
        output=dest,
        depth=depth,
        concurrent=concurrent,
        scroll=scroll,
        max_size=max_size,
        no_headless=not headless,
        no_resume=not resume,
        rate_limit=rate_limit,
    )


# ─── İlerleme çubuğu ─────────────────────────────────────────────────────────

class _ProgressPrinter:
    def __init__(self) -> None:
        self._start = time.time()
        self._last_line = ""

    def on_progress(self, pages_done: int, pages_total: int, assets: int) -> None:
        elapsed = time.time() - self._start
        pct = int(pages_done / pages_total * 100) if pages_total else 0
        filled = pct // 5
        bar = "█" * filled + "░" * (20 - filled)
        line = (
            f"\r  [{bar}] {pct:3d}%  "
            f"{pages_done}/{pages_total} sayfa  "
            f"{assets} asset  "
            f"{elapsed:.0f}s"
        )
        padding = " " * max(0, len(self._last_line) - len(line))
        sys.stderr.write(line + padding)
        sys.stderr.flush()
        self._last_line = line

    def finish(self) -> None:
        if self._last_line:
            sys.stderr.write("\n")
            sys.stderr.flush()


# ─── Ana fonksiyon ───────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    # Argüman yoksa veya yalnızca --flags varsa interaktif moda geç
    if argv is None and len(sys.argv) == 1:
        args = _interactive_mode()
    else:
        _print_banner()
        parser = _build_parser()
        args = parser.parse_args(argv)
        if not args.url:
            args = _interactive_mode()
        if not args.output:
            args.output = str(Path.cwd())

    _ensure_browser()

    output_dir = Path(args.output).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    opts = DownloadOptions(
        max_depth=args.depth,
        scroll_steps=args.scroll,
        headless=not args.no_headless,
        max_concurrent=args.concurrent,
        max_file_size_mb=args.max_size,
        rate_limit_ms=args.rate_limit,
        resume=not args.no_resume,
    )

    printer = _ProgressPrinter()
    ctx = DownloadContext(
        base_url=args.url,
        destination=output_dir,
        options=opts,
        log=print,
        on_progress=printer.on_progress,
    )

    print(f"\n  ▶  {args.url}")
    print(f"  📁 {output_dir}")
    print(f"  Derinlik: {args.depth}  |  Eş zamanlı: {args.concurrent}  |  Kaydırma: {args.scroll}\n")

    try:
        asyncio.run(SiteDownloader(ctx).run())
    except KeyboardInterrupt:
        printer.finish()
        print("\n  Durduruldu.")
        return 1
    except Exception as exc:
        printer.finish()
        print(f"\n  Hata: {exc}", file=sys.stderr)
        return 1

    printer.finish()
    s = ctx.stats
    print(f"\n  ✓ Tamamlandı — {s.pages_completed} sayfa, {s.assets_saved} asset, {s.errors} hata")
    print(f"  📁 {output_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
