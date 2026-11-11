#!/usr/bin/env python3
"""
sheet_writer.py — Write-back results to LOOKBOOKS_MASTER after generation.

Writes exactly three cells in a single batchUpdate call:
  Col A (Status)         → "Generated"
  Col I (Last Generated) → ISO 8601 timestamp, America/New_York
  Col J (Output HTML Link) → live URL

Does NOT:
  - read any sheet data
  - modify any column other than A, I, J
  - change row order
  - introduce retries

Public API
----------
write_back(service, sheet_id, row_index, timestamp, live_url) -> None

    Raises:
        SheetWriteError: if the Google Sheets API call fails.

Column reference (matches sheet_reader.py):
  A = index 0  — Status
  I = index 8  — Last Generated  (write-back only)
  J = index 9  — Output HTML Link (write-back only)
"""

import logging
from zoneinfo import ZoneInfo
from datetime import datetime

from googleapiclient.errors import HttpError

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

TAB_NAME       = "LOOKBOOKS_MASTER"
GENERATED_STATUS = "Generated"
TZ_EASTERN     = ZoneInfo("America/New_York")


# ── Exceptions ────────────────────────────────────────────────────────────────

class SheetWriteError(Exception):
    """Raised when the write-back call to Google Sheets fails."""


# ── Helpers ───────────────────────────────────────────────────────────────────

def _cell(col_letter: str, row_index: int) -> str:
    """Return an A1-notation cell address, e.g. _cell('I', 5) → 'LOOKBOOKS_MASTER!I5'."""
    return f"{TAB_NAME}!{col_letter}{row_index}"


def now_est_iso() -> str:
    """Return the current time in America/New_York as an ISO 8601 string."""
    return datetime.now(tz=TZ_EASTERN).isoformat(timespec="seconds")


# ── Public API ────────────────────────────────────────────────────────────────

def write_back(
    service,
    sheet_id: str,
    row_index: int,
    timestamp: str,
    live_url: str,
) -> None:
    """
    Write generation results back to a single row in LOOKBOOKS_MASTER.

    Performs a single batchUpdate touching exactly three cells:
      - Col A (Status)          ← "Generated"
      - Col I (Last Generated)  ← timestamp (ISO 8601, America/New_York)
      - Col J (Output HTML Link) ← live_url

    Args:
        service:    Sheets API resource from sheet_reader.build_sheets_service().
        sheet_id:   Spreadsheet ID (GOOGLE_SHEET_ID secret).
        row_index:  1-based row number from sheet_reader.get_ready_rows()
                    (the "row_index" key in each returned dict).
        timestamp:  ISO 8601 timestamp string (use now_est_iso() to generate).
        live_url:   Public URL of the generated lookbook page.

    Raises:
        SheetWriteError: if the Google Sheets API call fails.

    Note:
        - No sheet data is read by this function.
        - Only cols A, I, J are written. All other columns are untouched.
        - Row order is never altered.
    """
    body = {
        "valueInputOption": "RAW",
        "data": [
            {
                "range": _cell("A", row_index),
                "values": [[GENERATED_STATUS]],
            },
            {
                "range": _cell("I", row_index),
                "values": [[timestamp]],
            },
            {
                "range": _cell("J", row_index),
                "values": [[live_url]],
            },
        ],
    }

    logger.info(
        "write_back row=%d  status=%r  timestamp=%r  url=%r",
        row_index,
        GENERATED_STATUS,
        timestamp,
        live_url,
    )

    try:
        service.spreadsheets().values().batchUpdate(
            spreadsheetId=sheet_id,
            body=body,
        ).execute()
    except HttpError as exc:
        raise SheetWriteError(
            f"Google Sheets batchUpdate failed for row {row_index}: {exc}"
        ) from exc

    logger.info("write_back complete: row %d marked as %r", row_index, GENERATED_STATUS)
