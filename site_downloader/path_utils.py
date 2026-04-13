"""Utilities for mapping remote URLs to local filesystem paths."""
from __future__ import annotations

import hashlib
import mimetypes
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse, urlunparse

# Ensure common MIME types are recognized even if OS db is sparse
mimetypes.init()


@dataclass(frozen=True)
class LocalPathMapping:
    """Represents where a given URL should be stored locally."""

    url: str
    full_path: Path

    @property
    def directory(self) -> Path:
        return self.full_path.parent

    @property
    def relative_to_root(self) -> Path:
        """Return the path relative to the base download directory."""
        return Path(*self.full_path.parts[1:])


def _sanitize_segment(segment: str) -> str:
    safe = segment.replace("?", "_").replace(":", "_").replace("|", "_")
    safe = safe.replace("\x00", "")
    if not safe or safe in {".", ".."}:
        safe = "index"
    return safe


def _extension_from_mime(mime: str | None, fallback: str = "") -> str:
    if not mime:
        return fallback
    ext = mimetypes.guess_extension(mime.split(";")[0].strip())
    if not ext:
        return fallback
    return ext


def normalize_url(url: str) -> str:
    """Normalize a URL by stripping fragments and resolving default ports."""
    parsed = urlparse(url)
    netloc = parsed.netloc
    if parsed.scheme == "http" and parsed.port == 80:
        netloc = parsed.hostname or ""
    elif parsed.scheme == "https" and parsed.port == 443:
        netloc = parsed.hostname or ""
    normalized = parsed._replace(fragment="", netloc=netloc)
    return urlunparse(normalized)


def url_to_local_path(
    base_dir: Path,
    url: str,
    content_type: Optional[str] = None,
) -> LocalPathMapping:
    """Map a URL to a local filesystem path under ``base_dir``.

    The mapping attempts to mirror the remote path. Query strings are reduced to a
    hashed suffix to avoid extremely long filenames. Directories receive an
    ``index`` file with a suitable extension.
    """

    normalized = normalize_url(url)
    parsed = urlparse(normalized)

    host_dir = _sanitize_segment(parsed.netloc or "root")
    relative = Path(host_dir)

    path = parsed.path or "/"
    segments = [seg for seg in path.split("/") if seg]

    for seg in segments[:-1]:
        relative /= _sanitize_segment(seg)

    last_segment = segments[-1] if segments else ""
    if last_segment.endswith("/") or not last_segment:
        last_segment = "index"

    filename = _sanitize_segment(last_segment)

    suffix = Path(filename).suffix
    if not suffix:
        extension = _extension_from_mime(content_type, fallback=".html")
        filename = filename + extension

    if parsed.query:
        hashed = hashlib.sha1(parsed.query.encode("utf-8")).hexdigest()[:8]
        base_name = Path(filename).stem
        extension = Path(filename).suffix
        filename = f"{base_name}__{hashed}{extension}"

    relative /= filename
    full_path = (base_dir / relative).resolve()
    return LocalPathMapping(url=normalized, full_path=full_path)


def make_relative(from_path: Path, to_path: Path) -> str:
    """Return ``to_path`` relative to ``from_path`` directory."""
    import os
    from_dir = from_path.parent.resolve()
    return os.path.relpath(Path(to_path).resolve(), start=from_dir).replace("\\", "/")
