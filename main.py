#!/usr/bin/env python3
"""
main.py — HealthMerch Lookbook Generation Pipeline

End-to-end orchestration:
  1. Load environment variables
  2. Build Google Sheets service
  3. Read Ready rows from LOOKBOOKS_MASTER
  4. For each row:
       a. Transform hero + logo Drive URLs
       b. Validate hero + logo — skip row if BROKEN
       c. Fetch products by exact SKU list — skip row if any SKU missing/incomplete
       d. Generate intro_copy + description via AI
       e. Write data/{slug}.json and data/{slug}-config.json
       f. Run python scripts/build.py --slug {slug}
       g. Construct live URL
       h. Write back col A="Generated", col I=timestamp, col J=live URL

Rules:
  - Any failure at any step → skip row, no write-back, continue to next row
  - AI generates ONLY intro_copy and description
  - SKUs, links, hero image, logo, page title, CTA label, CTA URL are never modified
  - No retry logic in this file
  - All business logic lives in the imported modules — this file only orchestrates

Environment variables required:
  GOOGLE_APPLICATION_CREDENTIALS  Path to service account JSON key file
  GOOGLE_SHEET_ID                 Spreadsheet ID
  NETLIFY_SITE_URL                Base URL for constructing the live lookbook URL
                                  (e.g. https://site.netlify.app)
  ANTHROPIC_API_KEY               Consumed by generate_copy internally
  WEBSITE_API_URL                 Consumed by fetch_by_skus internally
  WEBSITE_GUID                    Consumed by fetch_by_skus internally
  WEBSITE_USERNAME                Consumed by fetch_by_skus internally
  WEBSITE_PASSWORD                Consumed by fetch_by_skus internally
  WEBSITE_LANGUAGE_GUID           Consumed by fetch_by_skus internally
  WEBSITE_CURRENCY_GUID           Consumed by fetch_by_skus internally
"""

import json
import logging
import os
import subprocess
import sys

from dotenv import load_dotenv

# ── Path setup — allow importing from scripts/ ───────────────────────────────
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "scripts"))

import drive_utils
import generate_copy as copy_module
import image_validator
import sheet_reader
import sheet_writer
from fetch_by_skus import clean_product, fetch_by_sku, get_token, is_complete_product

# ── Logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)-16s  %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger("main")

# ── Constants ─────────────────────────────────────────────────────────────────

# Fallback logo; matches build.py DEFAULT_LOGO_URL exactly.
DEFAULT_LOGO_URL = "https://www.healthmerch.com/media/wysiwyg/healthmerch-logo.png"

# Campaigns planned but not yet built — drives the "Coming up next" section on the index page.
# Kept in step with data/upcoming-campaigns.json, which scripts/build_index.py
# reads. Both feed the same two places on the index: the "Next campaign" card in
# the hero (first entry) and the upcoming grid at the foot of the page.
# Kept in step with data/upcoming-campaigns.json, which is what the index
# builder reads. Take a campaign off both once its page is published.
UPCOMING_CAMPAIGNS = [
    {"slug": "american-heart-month-27", "title": "American Heart Month", "date": "February 2027"},
]


# ── Env helpers ───────────────────────────────────────────────────────────────

def _require_env(name: str) -> str:
    """Return the value of an env var or exit with an error message."""
    value = os.environ.get(name)
    if not value:
        logger.error("Required environment variable %s is not set — aborting", name)
        sys.exit(1)
    return value


# ── Index page ────────────────────────────────────────────────────────────────

def _write_index_page(netlify_base: str, slugs: list[str]) -> None:
    """Write output/index.html.

    The page itself is built by scripts/build_index.py, which is also what CI
    runs. main.py used to carry a second copy of the builder, so a Sheet run
    quietly replaced the published page with an older shape.
    """
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "scripts"))
    import build_index

    upcoming = build_index._load_json(build_index.UPCOMING_FILE, [])
    html = build_index.build_index(slugs, upcoming)
    build_index.OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    build_index.OUTPUT_FILE.write_text(html, encoding="utf-8")
    logger.info("Wrote %s (%d pages)", build_index.OUTPUT_FILE, len(slugs))


def main() -> None:
    load_dotenv()

    logger.info("Starting lookbook generation run")

    # ── Step 1: Load and validate env vars ───────────────────────────────────
    creds_path      = _require_env("GOOGLE_APPLICATION_CREDENTIALS")
    sheet_id        = _require_env("GOOGLE_SHEET_ID")
    netlify_base    = _require_env("NETLIFY_SITE_URL").rstrip("/")

    # ── Step 2: Build Sheets service ─────────────────────────────────────────
    try:
        service = sheet_reader.build_sheets_service(creds_path)
    except Exception as exc:
        logger.error("Failed to build Google Sheets service: %s", exc)
        sys.exit(1)

    # ── Step 3: Get Ready rows ────────────────────────────────────────────────
    try:
        rows = sheet_reader.get_ready_rows(service, sheet_id)
    except (sheet_reader.SheetReadError, sheet_reader.SheetConfigError) as exc:
        logger.error("Cannot read sheet: %s", exc)
        sys.exit(1)

    if not rows:
        logger.info("No Ready rows found — nothing to do")
        sys.exit(0)

    os.makedirs("data", exist_ok=True)

    succeeded = 0
    skipped   = 0

    # ── Step 4: Process each row ─────────────────────────────────────────────
    for row in rows:
        row_index  = row["row_index"]
        slug       = row["slug"]
        event_name = row["event_name"]
        page_title = row["page_title"]
        sku_list   = row["sku_list"]

        logger.info(
            "[row %d] slug=%r  skus=%d  event=%r",
            row_index, slug, len(sku_list), event_name,
        )

        # ── 4a–4b: Transform + validate images ───────────────────────────────
        hero_url = drive_utils.transform_drive_url(row["hero_image_url"])
        logo_url = drive_utils.transform_drive_url(row["healthmerch_logo_url"])

        try:
            safe_hero, safe_logo, should_proceed = image_validator.validate_header_images(
                hero_url, logo_url, DEFAULT_LOGO_URL
            )
        except Exception as exc:
            logger.error(
                "[row %d] slug=%r: image validation raised unexpectedly: %s — skipping row, no write-back",
                row_index, slug, exc,
            )
            skipped += 1
            continue

        if not should_proceed:
            logger.error(
                "[row %d] slug=%r: image validation failed (BROKEN) — skipping row, no write-back",
                row_index, slug,
            )
            skipped += 1
            continue

        logger.info(
            "[row %d] Images validated: hero=%s  logo=%s",
            row_index,
            f"PRESENT ({safe_hero[:60]})" if safe_hero else "MISSING (omitted from build)",
            f"default ({DEFAULT_LOGO_URL[:60]})" if safe_logo == DEFAULT_LOGO_URL else f"CUSTOM ({safe_logo[:60]})",
        )

        # ── 4c: Fetch products by exact SKU list ──────────────────────────────
        if not sku_list:
            logger.error(
                "[row %d] slug=%r: SKU list is empty — skipping row, no write-back",
                row_index, slug,
            )
            skipped += 1
            continue

        try:
            token = get_token()
        except Exception as exc:
            logger.error(
                "[row %d] slug=%r: failed to obtain API token: %s — skipping row, no write-back",
                row_index, slug, exc,
            )
            skipped += 1
            continue

        logger.info("[row %d] Fetching %d products via SKU API", row_index, len(sku_list))

        products = []

        for sku in sku_list:
            try:
                product = fetch_by_sku(token, sku)
            except Exception as exc:
                logger.warning(
                    "[row %d] slug=%r: unexpected error fetching SKU %r: %s — skipping this SKU",
                    row_index, slug, sku, exc,
                )
                continue

            if product is None:
                logger.warning(
                    "[row %d] slug=%r: SKU %r not found in product API — skipping this SKU",
                    row_index, slug, sku,
                )
                continue

            if not is_complete_product(product):
                logger.warning(
                    "[row %d] slug=%r: SKU %r found but missing required fields "
                    "(image, link, price, or name) — skipping this SKU",
                    row_index, slug, sku,
                )
                continue

            products.append(clean_product(product))

        if not products:
            logger.error(
                "[row %d] slug=%r: no valid products found from SKU list — skipping row, no write-back",
                row_index, slug,
            )
            skipped += 1
            continue

        logger.info("[row %d] All %d SKUs fetched successfully", row_index, len(products))

        # ── 4d: Generate AI copy ──────────────────────────────────────────────
        try:
            copy = copy_module.generate_copy(event_name=event_name, slug=slug)
        except copy_module.CopyGenerationError as exc:
            logger.error(
                "[row %d] slug=%r: copy generation failed: %s — skipping row, no write-back",
                row_index, slug, exc,
            )
            skipped += 1
            continue

        logger.info(
            "[row %d] Copy generated (intro_copy=%d chars, description=%d sentences)",
            row_index, len(copy["intro_copy"]), len(copy["description"]),
        )

        # ── 4e: Write data files ──────────────────────────────────────────────
        data_file   = os.path.join("data", f"{slug}.json")
        config_file = os.path.join("data", f"{slug}-config.json")

        config = {
            "page_title":            copy.get("page_title") or page_title,
            "eyebrow":               event_name,
            "cta_label":             row["cta_label"],
            "cta_url":               row["cta_url"],
            "hero_image_url":        safe_hero,
            "healthmerch_logo_url":  safe_logo,
            "intro_copy":            copy["intro_copy"],
            "description":           copy["description"],
        }

        try:
            with open(data_file, "w", encoding="utf-8") as f:
                json.dump(products, f, indent=2, ensure_ascii=False)
            logger.info("[row %d] Wrote %s (%d products)", row_index, data_file, len(products))

            with open(config_file, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
            logger.info("[row %d] Wrote %s", row_index, config_file)
        except OSError as exc:
            logger.error(
                "[row %d] slug=%r: failed to write data files: %s — skipping row, no write-back",
                row_index, slug, exc,
            )
            skipped += 1
            continue

        # ── 4f: Run build.py ──────────────────────────────────────────────────
        build_cmd = ["python", "scripts/build.py", "--slug", slug]
        logger.info("[row %d] Running: %s", row_index, " ".join(build_cmd))

        try:
            result = subprocess.run(build_cmd, capture_output=True, text=True)
        except Exception as exc:
            logger.error(
                "[row %d] slug=%r: failed to launch build.py: %s — skipping row, no write-back",
                row_index, slug, exc,
            )
            skipped += 1
            continue

        if result.returncode != 0:
            logger.error(
                "[row %d] slug=%r: build.py exited %d — skipping row, no write-back\n%s",
                row_index, slug, result.returncode,
                result.stderr.strip() or result.stdout.strip(),
            )
            skipped += 1
            continue

        logger.info("[row %d] build.py exited 0", row_index)

        # ── 4g–4h: Write back to sheet ────────────────────────────────────────
        live_url  = f"{netlify_base}/{slug}"
        timestamp = sheet_writer.now_est_iso()

        try:
            sheet_writer.write_back(service, sheet_id, row_index, timestamp, live_url)
        except sheet_writer.SheetWriteError as exc:
            logger.error(
                "[row %d] slug=%r: sheet write-back failed: %s — "
                "HTML was built but row stays Ready",
                row_index, slug, exc,
            )
            skipped += 1
            continue

        succeeded += 1
        logger.info("[row %d] SUCCESS — %s", row_index, live_url)

    # ── Write index.html landing page ─────────────────────────────────────────
    # Read the full existing slug list from data/index-slugs.json, append any
    # newly built slugs that aren't already there, persist the updated list,
    # then rebuild index.html with the complete set.
    if succeeded > 0:
        index_slugs_path = os.path.join("data", "index-slugs.json")
        try:
            with open(index_slugs_path, encoding="utf-8") as _f:
                all_slugs: list[str] = json.load(_f)
        except (FileNotFoundError, json.JSONDecodeError):
            all_slugs = []

        # The first six slugs are the "Current campaigns" grid, so a page built
        # in this run belongs at the front, not behind the whole back catalogue.
        newly_built = [r["slug"] for r in rows if r["slug"] and r["slug"] not in all_slugs]
        all_slugs = newly_built + all_slugs

        with open(index_slugs_path, "w", encoding="utf-8") as _f:
            json.dump(all_slugs, _f, indent=2)

        _write_index_page(netlify_base, all_slugs)

    # ── Summary ───────────────────────────────────────────────────────────────
    total = succeeded + skipped
    logger.info(
        "Run complete: %d processed, %d succeeded, %d skipped",
        total, succeeded, skipped,
    )


if __name__ == "__main__":
    main()
