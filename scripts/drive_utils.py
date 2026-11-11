#!/usr/bin/env python3
"""
drive_utils.py — Transform Google Drive share links to browser-safe image URLs.

Supported input formats (all transform to the canonical thumbnail URL):

  1. https://drive.google.com/file/d/{ID}/view
  2. https://drive.google.com/file/d/{ID}/view?usp=sharing
  3. https://drive.google.com/file/d/{ID}/view?usp=drive_link
  4. https://drive.google.com/open?id={ID}
  5. https://drive.google.com/uc?export=view&id={ID}   — legacy embed, converted
  6. https://drive.google.com/uc?id={ID}               — legacy embed, converted

All recognised Drive formats are rewritten to:
  https://drive.google.com/thumbnail?id={ID}&sz=w800

WHY thumbnail instead of uc?export=view:
  uc?export=view redirects through Google's auth/virus-scan pages and returns
  text/html (not image/*) when requested by servers or CI runners — even for
  publicly shared files.  The thumbnail endpoint returns image/jpeg directly,
  works from both servers and browsers, and passes image_validator correctly.

Non-Drive URLs (CloudFront, Cloudinary, direct HTTPS CDN, etc.) are returned
unchanged.

Empty input or non-string input returns "".
"""

import re
from urllib.parse import parse_qs, urlparse

# Matches /file/d/{ID}/ in any Drive file URL path
_FILE_PATH_RE = re.compile(r"drive\.google\.com/file/d/([A-Za-z0-9_\-]+)")

# Matches drive.google.com/open?id={ID}
_OPEN_ID_RE = re.compile(r"drive\.google\.com/open\?.*[?&]id=([A-Za-z0-9_\-]+)")

_EMBED_BASE = "https://drive.google.com/thumbnail?id={file_id}&sz=w800"


def _extract_drive_file_id(url: str) -> str | None:
    """
    Extract the file ID from any recognised Google Drive URL format.

    Returns the file ID string, or None if no pattern matches (not a Drive URL
    or unrecognised Drive URL variant).
    """
    # Format 1-3: /file/d/{ID}/
    m = _FILE_PATH_RE.search(url)
    if m:
        return m.group(1)

    # Format 4: /open?id={ID}
    m = _OPEN_ID_RE.search(url)
    if m:
        return m.group(1)

    # Formats 5-6: /uc?export=view&id={ID} or /uc?id={ID}
    parsed = urlparse(url)
    if "drive.google.com" in parsed.netloc and parsed.path.rstrip("/") == "/uc":
        qs = parse_qs(parsed.query)
        file_id = qs.get("id", [None])[0]
        if file_id:
            return file_id

    return None


def transform_drive_url(url: str) -> str:
    """
    Transform a Google Drive share link to a browser-safe embeddable image URL.

    Args:
        url: Raw URL string from sheet col K (Hero Image URL) or col L
             (HealthMerch Logo URL). May be a Drive share link, a direct CDN
             URL, or an empty string.

    Returns:
        - Empty string if url is empty, None, or not a string.
        - Canonical embed URL (uc?export=view&id={ID}) if url is any supported
          Drive format, including already-correct embed URLs (normalised).
        - url unchanged if url is a non-Drive HTTPS URL.
        - url unchanged if url is a Drive URL but in an unrecognised format
          (image_validator will flag it as BROKEN).
    """
    if not url or not isinstance(url, str):
        return ""

    url = url.strip()
    if not url:
        return ""

    # Only transform drive.google.com URLs
    if "drive.google.com" not in url:
        return url

    file_id = _extract_drive_file_id(url)
    if file_id:
        return _EMBED_BASE.format(file_id=file_id)

    # Drive URL but unrecognised pattern — return as-is; image_validator will
    # report it as BROKEN so the operator can correct the URL in the sheet.
    return url
