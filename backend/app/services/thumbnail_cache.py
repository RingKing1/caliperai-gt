"""Disk-cached image thumbnails.

The first request for a given (source file, size, quality) variant is
generated with Pillow and stored in a sharded cache directory; subsequent
requests are served straight from disk via sendfile. The source file's
mtime/size are part of the cache key, so a replaced source invalidates its
variants automatically.

The cache lives outside the (possibly read-only) data mounts and is safe to
delete at any time — missing variants are regenerated on the next request.
"""
from __future__ import annotations

import hashlib
import logging
import os
import tempfile
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

CACHE_ROOT = Path(os.environ.get("THUMB_CACHE_DIR", "/tmp/caliperai-thumbs"))

_MEDIA_TYPES = {
    ".jpg": ("image/jpeg", ".jpg"),
    ".jpeg": ("image/jpeg", ".jpg"),
    ".png": ("image/png", ".png"),
    ".webp": ("image/webp", ".webp"),
}

# Per-process lock so concurrent requests for the same variant generate it
# once. O_EXCL temp files guard against multi-process workers.
_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def _lock_for(key: str) -> threading.Lock:
    with _locks_guard:
        lock = _locks.get(key)
        if lock is None:
            lock = threading.Lock()
            _locks[key] = lock
        return lock


def _cache_path(src: Path, width: int | None, height: int | None, quality: int) -> Path | None:
    ext = src.suffix.lower()
    media = _MEDIA_TYPES.get(ext)
    if media is None:
        return None
    try:
        stat = src.stat()
    except OSError:
        return None
    key_src = f"{src.resolve()}:{stat.st_mtime_ns}:{stat.st_size}:{width or ''}x{height or ''}:q{quality}"
    key = hashlib.sha256(key_src.encode()).hexdigest()
    return CACHE_ROOT / key[:2] / key[2:4] / f"{key}{media[1]}"


def get_or_create_thumbnail(
    src: Path,
    width: int | None = None,
    height: int | None = None,
    quality: int = 85,
) -> tuple[Path, str, tuple[int, int], tuple[int, int]] | None:
    """Return (cached_file, media_type, original_wh, output_wh).

    Returns None when the source type has no resizable encoder (caller should
    stream the original instead).
    """
    ext = src.suffix.lower()
    media_info = _MEDIA_TYPES.get(ext)
    if media_info is None or (width is None and height is None):
        return None
    media_type, _ = media_info

    target = _cache_path(src, width, height, quality)
    if target is None:
        return None
    if target.exists():
        from PIL import Image

        with Image.open(target) as im:
            return target, media_type, im.size, im.size

    lock = _lock_for(target.name)
    with lock:
        if target.exists():
            from PIL import Image

            with Image.open(target) as im:
                return target, media_type, im.size, im.size

        from PIL import Image

        img = Image.open(src)
        original = img.size
        if img.mode == "RGBA" and ext in (".jpg", ".jpeg"):
            background = Image.new("RGB", img.size, (255, 255, 255))
            background.paste(img, mask=img.split()[3])
            img = background

        orig_w, orig_h = img.size
        if width and height:
            img.thumbnail((width, height), Image.Resampling.LANCZOS)
        elif width:
            img = img.resize((width, max(1, int(orig_h * width / orig_w))), Image.Resampling.LANCZOS)
        elif height:
            img = img.resize((max(1, int(orig_w * height / orig_h)), height), Image.Resampling.LANCZOS)
        output = img.size

        # Never upscale: serve the original file directly when the requested
        # variant is at least as large as the source.
        if output[0] >= orig_w and output[1] >= orig_h:
            return src, media_type, (orig_w, orig_h), (orig_w, orig_h)

        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(dir=target.parent, prefix=".tmp-", suffix=target.suffix)
        os.close(fd)
        tmp = Path(tmp_name)
        try:
            if ext in (".jpg", ".jpeg"):
                img.convert("RGB").save(tmp, format="JPEG", quality=quality, optimize=True)
            elif ext == ".png":
                img.save(tmp, format="PNG", optimize=True)
            elif ext == ".webp":
                img.save(tmp, format="WEBP", quality=quality)
            os.replace(tmp, target)
        except Exception:
            tmp.unlink(missing_ok=True)
            raise

    logger.debug("[THUMB] generated %s -> %s (%dx%d)", src.name, target.name, output[0], output[1])
    return target, media_type, original, output
