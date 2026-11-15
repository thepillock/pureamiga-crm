"""Uploading, checking and serving job attachments (photos and scanned letters)."""
import re
from pathlib import Path

from django.conf import settings

# Decided from the file's own first bytes, never from what the browser claims (so nothing can pose as an image).
SIGNATURES = [
    (b"\xff\xd8\xff", "image/jpeg", ".jpg"),
    (b"\x89PNG\r\n\x1a\n", "image/png", ".png"),
    (b"GIF87a", "image/gif", ".gif"),
    (b"GIF89a", "image/gif", ".gif"),
    (b"%PDF-", "application/pdf", ".pdf"),
]


def sniff(head):
    """(content_type, extension) for an allowed file, or None."""
    for magic, ctype, ext in SIGNATURES:
        if head.startswith(magic):
            return ctype, ext
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp", ".webp"
    if head[4:8] == b"ftyp" and head[8:12] in (b"heic", b"heix", b"mif1", b"msf1", b"heis", b"hevc"):
        return "image/heic", ".heic"
    return None


def safe_name(name, ext):
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", Path(name or "upload").stem).strip("-.")[:60] or "upload"
    return f"{stem}{ext}"


def max_bytes():
    return settings.MAX_ATTACHMENT_BYTES
