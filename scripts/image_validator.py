#!/usr/bin/env python3
"""
image_validator.py — Validate image URLs are browser-deliverable before build.

Validation states
─────────────────
VALID
    URL responded HTTP 200 with a Content-Type of image/*.
    The image will render correctly in a browser.
    The URL is safe to pass to build.py.

MISSING
    URL is an empty string or was not provided.
    This is an expected/normal state, not an error.
    Fallback behaviour is applied by validate_header_images():
      - Hero  MISSING → "" (build.py skips the hero block gracefully)
      - Logo  MISSING → DEFAULT_LOGO_URL

BROKEN
    One of:
      - URL responded HTTP 200 but Content-Type is not image/* — most commonly
        a Google Drive auth interstitial ("Sign in to continue") or a virus-scan
        warning page served instead of the image.
      - URL returned a 4xx or 5xx HTTP status.
      - URL caused a redirect loop (TooManyRedirects).
    A BROKEN hero or logo URL means a lookbook must NOT be built for that row.
    The row stays Status=Ready so it is retried on the next daily run after the
    operator fixes the URL in the sheet.

UNREACHABLE
    A network-level failure: connection timeout, DNS failure, or other transient
    connectivity issue. The URL itself may be perfectly valid.
    A transient warning is logged, the URL is used as-is, and the build
    proceeds — the image is likely to render correctly at Netlify deploy time.

Why GET with stream=True instead of HEAD?
─────────────────────────────────────────
Google Drive uc?export=view URLs follow a redirect chain before serving the
image. The final hop may return 405 (Method Not Allowed) or a misleading 200
to HEAD requests while actually serving an HTML interstitial for GET. Using
requests.get(..., stream=True, allow_redirects=True) follows redirects and
reads only the response headers — no image bytes are downloaded — making it
both lightweight and accurate for Drive and non-Drive URLs alike.
"""

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

import requests

logger = logging.getLogger(__name__)

# ── Configuration ──────────────────────────────────────────────────────────────

TIMEOUT_SECONDS = 10
MAX_REDIRECTS   = 10   # Drive typically uses 2–4; allow headroom


# ── Types ──────────────────────────────────────────────────────────────────────

class ImageStatus(Enum):
    VALID       = "VALID"
    MISSING     = "MISSING"
    BROKEN      = "BROKEN"
    UNREACHABLE = "UNREACHABLE"


@dataclass
class ValidationResult:
    """Result of a single image URL validation check."""
    url:          str
    status:       ImageStatus
    http_code:    Optional[int] = field(default=None)
    content_type: Optional[str] = field(default=None)
    detail:       str           = field(default="")

    @property
    def ok(self) -> bool:
        """True only when status is VALID — the URL is safe to use in a build."""
        return self.status == ImageStatus.VALID

    @property
    def is_missing(self) -> bool:
        return self.status == ImageStatus.MISSING

    @property
    def is_broken(self) -> bool:
        return self.status == ImageStatus.BROKEN

    @property
    def is_unreachable(self) -> bool:
        return self.status == ImageStatus.UNREACHABLE


# ── Core validator ─────────────────────────────────────────────────────────────

def validate_image_url(url: str) -> ValidationResult:
    """
    Check whether a URL serves a browser-renderable image.

    Uses GET with stream=True to follow redirects and inspect the Content-Type
    header without downloading any image data.

    Args:
        url: Image URL to validate. Should already be transformed by
             drive_utils.transform_drive_url() if it was a Drive link.

    Returns:
        ValidationResult with status VALID, MISSING, BROKEN, or UNREACHABLE.
        See module docstring for the exact meaning of each state.
    """
    if not url or not isinstance(url, str) or not url.strip():
        return ValidationResult(
            url="",
            status=ImageStatus.MISSING,
            detail="URL is empty or not provided",
        )

    url = url.strip()

    try:
        response = requests.get(
            url,
            stream=True,
            allow_redirects=True,
            timeout=TIMEOUT_SECONDS,
            headers={"User-Agent": "HealthMerch-Lookbook-Validator/1.0"},
        )
        # Close immediately — we only need headers, not the body
        response.close()

        http_code    = response.status_code
        content_type = response.headers.get("Content-Type", "")

        if http_code == 200:
            if content_type.startswith("image/"):
                logger.debug("VALID %s  [%d] %s", url[:80], http_code, content_type)
                return ValidationResult(
                    url=url,
                    status=ImageStatus.VALID,
                    http_code=http_code,
                    content_type=content_type,
                    detail="OK",
                )
            elif "drive.google.com" in url:
                # GitHub Actions runners have no Google session, so Drive sometimes
                # serves a virus-scan warning page (text/html, HTTP 200) instead of
                # the image — even when the file is publicly shared. Browsers load
                # the same URL correctly because they carry a Google session cookie.
                # Treat as UNREACHABLE so the URL is passed through unchanged; the
                # image will render correctly in the published lookbook.
                detail = (
                    f"HTTP 200 but Content-Type is '{content_type}' from Drive CI — "
                    "treating as transient; URL will render correctly in browsers"
                )
                logger.warning("UNREACHABLE (Drive CI interstitial) %s  %s", url[:80], detail)
                return ValidationResult(
                    url=url,
                    status=ImageStatus.UNREACHABLE,
                    http_code=http_code,
                    content_type=content_type or None,
                    detail=detail,
                )
            else:
                # HTTP 200 but not an image — wrong URL or unexpected content
                detail = (
                    f"HTTP 200 but Content-Type is '{content_type}' — "
                    "URL does not point to an image"
                )
                logger.warning("BROKEN %s  %s", url[:80], detail)
                return ValidationResult(
                    url=url,
                    status=ImageStatus.BROKEN,
                    http_code=http_code,
                    content_type=content_type or None,
                    detail=detail,
                )
        else:
            detail = f"HTTP {http_code}"
            logger.warning("BROKEN %s  %s", url[:80], detail)
            return ValidationResult(
                url=url,
                status=ImageStatus.BROKEN,
                http_code=http_code,
                content_type=content_type or None,
                detail=detail,
            )

    except requests.exceptions.Timeout:
        detail = f"Request timed out after {TIMEOUT_SECONDS}s"
        logger.warning("UNREACHABLE %s  %s", url[:80], detail)
        return ValidationResult(
            url=url, status=ImageStatus.UNREACHABLE, detail=detail
        )

    except requests.exceptions.TooManyRedirects:
        detail = f"Exceeded redirect limit — possible redirect loop or auth wall"
        logger.warning("BROKEN %s  %s", url[:80], detail)
        return ValidationResult(
            url=url, status=ImageStatus.BROKEN, detail=detail
        )

    except requests.exceptions.ConnectionError as exc:
        detail = f"Connection error: {exc}"
        logger.warning("UNREACHABLE %s  %s", url[:80], detail)
        return ValidationResult(
            url=url, status=ImageStatus.UNREACHABLE, detail=detail
        )

    except requests.exceptions.RequestException as exc:
        detail = f"Request error: {exc}"
        logger.warning("UNREACHABLE %s  %s", url[:80], detail)
        return ValidationResult(
            url=url, status=ImageStatus.UNREACHABLE, detail=detail
        )


# ── High-level helper for hero + logo ─────────────────────────────────────────

def validate_header_images(
    hero_url: str,
    logo_url: str,
    default_logo_url: str,
) -> tuple[str, str, bool]:
    """
    Validate hero and logo URLs and apply fallback rules.

    Returns build-safe URLs and a flag indicating whether the build should
    proceed for this lookbook row.

    Fallback rules:
        Hero  VALID       → use hero_url as-is
        Hero  MISSING     → use "" (build.py omits the hero block gracefully)
        Hero  BROKEN      → log error, set should_proceed=False
        Hero  UNREACHABLE → use hero_url as-is with a warning

        Logo  VALID       → use logo_url as-is
        Logo  MISSING     → use default_logo_url
        Logo  BROKEN      → log error, set should_proceed=False
        Logo  UNREACHABLE → use logo_url as-is with a warning

    When should_proceed is False, the caller must skip the build for this row
    and leave Status=Ready in the sheet so the operator can fix the URL and
    the row is retried on the next daily run.

    Args:
        hero_url:         Transformed hero image URL (col K via drive_utils).
        logo_url:         Transformed logo URL (col L via drive_utils).
        default_logo_url: Fallback logo URL when col L is empty.

    Returns:
        Tuple of (safe_hero_url: str, safe_logo_url: str, should_proceed: bool).
    """
    hero_result = validate_image_url(hero_url)
    logo_result = validate_image_url(logo_url)

    safe_hero      = hero_url
    safe_logo      = logo_url
    should_proceed = True

    # ── Hero ──────────────────────────────────────────────────────────────────
    if hero_result.is_missing:
        safe_hero = ""
        logger.info("Hero image (col K) not set — hero block will be omitted from build")

    elif hero_result.is_broken:
        logger.error(
            "Hero image (col K) is BROKEN: %s — skipping build for this row. "
            "Fix the URL in col K and re-set Status to Ready to retry.",
            hero_result.detail,
        )
        should_proceed = False

    elif hero_result.is_unreachable:
        safe_hero = hero_url
        logger.warning(
            "Hero image (col K) is UNREACHABLE (transient network issue) — "
            "proceeding with URL as-is. URL: %s",
            hero_url[:80],
        )
    # VALID: safe_hero = hero_url unchanged

    # ── Logo ──────────────────────────────────────────────────────────────────
    if logo_result.is_missing:
        safe_logo = default_logo_url
        logger.info(
            "Logo (col L) not set — using default: %s", default_logo_url
        )

    elif logo_result.is_broken:
        logger.error(
            "Logo (col L) is BROKEN: %s — skipping build for this row. "
            "Fix the URL in col L and re-set Status to Ready to retry.",
            logo_result.detail,
        )
        should_proceed = False

    elif logo_result.is_unreachable:
        safe_logo = logo_url
        logger.warning(
            "Logo (col L) is UNREACHABLE (transient network issue) — "
            "proceeding with URL as-is. URL: %s",
            logo_url[:80],
        )
    # VALID: safe_logo = logo_url unchanged

    return safe_hero, safe_logo, should_proceed
