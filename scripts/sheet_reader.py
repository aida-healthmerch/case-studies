#!/usr/bin/env python3
"""
sheet_reader.py — Read LOOKBOOKS_MASTER and return rows where Status = "Ready".

Exact column mapping (fixed positional, never remapped):

  Col A (index  0) = Status                 — read + write-back
  Col B (index  1) = Event Name             — read
  Col C (index  2) = Slug                   — read
  Col D (index  3) = Page Title             — read verbatim (AI must not override)
  Col E (index  4) = CTA Label              — read verbatim (AI must not override)
  Col F (index  5) = CTA URL               — read verbatim (AI must not override)
  Col G (index  6) = SKU List              — read verbatim (AI must not override)
  Col H (index  7) = (reserved, not read)
  Col I (index  8) = Last Generated        — write-back only, not read here
  Col J (index  9) = Output HTML Link      — write-back only, not read here
  Col K (index 10) = Hero Image URL        — read (raw Drive link; transform via drive_utils)
  Col L (index 11) = HealthMerch Logo URL  — read (raw Drive link; transform via drive_utils)

The header row is validated against these expected positions at runtime.
If any expected header is missing or mispositioned, SheetConfigError is raised
before any row data is returned — preventing silent miscategorisation.
"""

import logging
from typing import Any

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

TAB_NAME    = "LOOKBOOKS_MASTER"
SHEET_RANGE = f"{TAB_NAME}!A:L"   # Read cols A–L only; I and J intentionally included for position alignment
READY_STATUS = "Ready"

# Fixed positional column indices (0-based). Never change without updating the
# sheet structure and redeploying.
COL_STATUS    = 0   # A
COL_EVENT     = 1   # B
COL_SLUG      = 2   # C
COL_TITLE     = 3   # D  — verbatim from sheet, AI must not override
COL_CTA_LABEL = 4   # E  — verbatim from sheet, AI must not override
COL_CTA_URL   = 5   # F  — verbatim from sheet, AI must not override
COL_SKUS      = 6   # G  — verbatim from sheet, AI must not override
COL_NOTES     = 7   # H  — optional freetext instructions for copy, grouping, and filters
# COL_I       = 8   — Last Generated, write-back only
# COL_J       = 9   — Output HTML Link, write-back only
COL_HERO      = 10  # K  — raw Drive link; transform via drive_utils before use
COL_LOGO      = 11  # L  — raw Drive link; transform via drive_utils before use

# Expected header names keyed by column index, used only for layout validation.
EXPECTED_HEADERS: dict[int, str] = {
    COL_STATUS:    "Status",
    COL_EVENT:     "Event Name",
    COL_SLUG:      "Slug",
    COL_TITLE:     "Page Title",
    COL_CTA_LABEL: "CTA Label",
    COL_CTA_URL:   "CTA URL",
    COL_SKUS:      "SKU List",
    COL_NOTES:     "Notes",
    COL_HERO:      "Hero Image URL",
    COL_LOGO:      "HealthMerch Logo URL",
}

GOOGLE_SHEETS_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


# ── Exceptions ────────────────────────────────────────────────────────────────

class SheetConfigError(Exception):
    """Raised when the sheet column layout does not match the expected mapping."""


class SheetReadError(Exception):
    """Raised when the sheet cannot be read due to a Google Sheets API error."""


# ── Auth ──────────────────────────────────────────────────────────────────────

def build_sheets_service(credentials_path: str):
    """
    Authenticate with a service account and return a Sheets API v4 resource.

    Args:
        credentials_path: Path to the service account JSON key file
                          (e.g. "gcloud-key.json" written by GitHub Actions).

    Returns:
        googleapiclient.discovery.Resource for Sheets v4.

    Raises:
        FileNotFoundError: if credentials_path does not exist.
        google.auth.exceptions.GoogleAuthError: on authentication failure.
    """
    creds = Credentials.from_service_account_file(
        credentials_path,
        scopes=GOOGLE_SHEETS_SCOPES,
    )
    return build("sheets", "v4", credentials=creds)


# ── Internal helpers ──────────────────────────────────────────────────────────

def _get_cell(row: list[str], col_idx: int) -> str:
    """Return the stripped cell value at col_idx, or "" if the column is absent."""
    if col_idx < len(row):
        return row[col_idx].strip()
    return ""


def _validate_headers(header_row: list[str]) -> None:
    """
    Confirm the header row matches expected column positions exactly.

    Raises:
        SheetConfigError: listing every mismatched column if any are wrong.
    """
    errors: list[str] = []
    for idx, expected_name in EXPECTED_HEADERS.items():
        actual = header_row[idx].strip() if idx < len(header_row) else "(column absent)"
        if actual != expected_name:
            col_letter = chr(65 + idx)
            errors.append(
                f"Column {col_letter} (index {idx}): "
                f"expected '{expected_name}', found '{actual}'"
            )
    if errors:
        raise SheetConfigError(
            "Sheet column layout does not match expected mapping. "
            "Fix the sheet or update the column constants in sheet_reader.py:\n"
            + "\n".join(f"  - {e}" for e in errors)
        )


def _parse_sku_list(raw: str) -> list[str]:
    """
    Parse a comma- or newline-separated SKU string into a clean list.

    Args:
        raw: Raw cell value from col G (SKU List).

    Returns:
        List of stripped, non-empty SKU strings. Order preserved.
        Empty list if raw is empty.
    """
    if not raw:
        return []
    return [s.strip() for s in raw.replace("\n", ",").split(",") if s.strip()]


# ── Public API ────────────────────────────────────────────────────────────────

def get_ready_rows(service, sheet_id: str) -> list[dict[str, Any]]:
    """
    Read LOOKBOOKS_MASTER and return all rows where col A (Status) == "Ready".

    Each returned dict has the following keys. All string values are stripped.
    No field is modified by AI — these are raw sheet values:

        row_index            (int)       1-based sheet row number, for write-back
        status               (str)       col A — always "Ready" for returned rows
        event_name           (str)       col B
        slug                 (str)       col C
        page_title           (str)       col D — verbatim, AI must not override
        cta_label            (str)       col E — verbatim, AI must not override
        cta_url              (str)       col F — verbatim, AI must not override
        sku_list             (list[str]) col G — parsed into individual SKUs
        hero_image_url       (str)       col K — raw Drive link, not yet transformed
        healthmerch_logo_url (str)       col L — raw Drive link, not yet transformed

    Note: hero_image_url and healthmerch_logo_url are the raw values from the
    sheet. Callers must pass them through drive_utils.transform_drive_url()
    before use, then validate with image_validator.validate_header_images().

    Args:
        service:  Sheets API resource from build_sheets_service().
        sheet_id: Spreadsheet ID (GOOGLE_SHEET_ID secret).

    Returns:
        List of row dicts as above. Returns [] if no Ready rows exist.

    Raises:
        SheetReadError:   on Google Sheets API failure.
        SheetConfigError: if the sheet header row does not match expected layout.
    """
    try:
        result = (
            service.spreadsheets()
            .values()
            .get(spreadsheetId=sheet_id, range=SHEET_RANGE)
            .execute()
        )
    except HttpError as exc:
        raise SheetReadError(f"Google Sheets API error: {exc}") from exc

    rows = result.get("values", [])

    if not rows:
        logger.warning("Sheet returned no rows — tab may be empty")
        return []

    header_row = rows[0]
    _validate_headers(header_row)

    ready: list[dict[str, Any]] = []

    for row_offset, row in enumerate(rows[1:], start=2):
        if _get_cell(row, COL_STATUS) != READY_STATUS:
            continue

        entry: dict[str, Any] = {
            "row_index":             row_offset,
            "status":                _get_cell(row, COL_STATUS),
            "event_name":            _get_cell(row, COL_EVENT),
            "slug":                  _get_cell(row, COL_SLUG),
            "page_title":            _get_cell(row, COL_TITLE),
            "cta_label":             _get_cell(row, COL_CTA_LABEL),
            "cta_url":               _get_cell(row, COL_CTA_URL),
            "sku_list":              _parse_sku_list(_get_cell(row, COL_SKUS)),
            "notes":                 _get_cell(row, COL_NOTES),
            "hero_image_url":        _get_cell(row, COL_HERO),
            "healthmerch_logo_url":  _get_cell(row, COL_LOGO),
        }

        logger.info(
            "Ready row %d: slug=%r  skus=%d  event=%r",
            row_offset,
            entry["slug"],
            len(entry["sku_list"]),
            entry["event_name"],
        )
        ready.append(entry)

    logger.info(
        "Sheet scan complete: %d Ready row(s) found in %s", len(ready), TAB_NAME
    )
    return ready
