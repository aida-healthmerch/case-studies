#!/usr/bin/env python3
"""
validate.py — HealthMerch Lookbook Data Validator

Validates data/pride-2026.json against the canonical schema.
Run from the repo root:

    python scripts/validate.py

Exits 0 on pass. Exits 1 on any failure, with a full error report.
Used as the first step in the build pipeline — a failing validator
stops the build before any HTML is generated.
"""
import json
import os
import sys

DATA_FILE = "data/pride-2026.json"

REQUIRED_FIELDS = {"sku", "name", "category", "price", "image_url", "product_url"}

ALLOWED_CATEGORIES = {
    "Apparel",
    "Bags",
    "Drinkware",
    "Wellness",
    "Technology",
    "Office Supplies",
    "Outdoor",
    "Stickers",
}


def main():
    errors = []

    print(f"Validating {DATA_FILE}...")

    # Check 1 — File exists and is readable
    if not os.path.isfile(DATA_FILE):
        print(f"\nFAILED — file not found: {DATA_FILE}")
        sys.exit(1)
    print("  \u2713 File readable")

    # Check 2 — Valid JSON and top-level array
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            products = json.load(f)
    except json.JSONDecodeError as e:
        print(f"\nFAILED — invalid JSON: {e}")
        sys.exit(1)

    if not isinstance(products, list):
        print("\nFAILED — expected a JSON array at top level")
        sys.exit(1)
    print("  \u2713 Valid JSON")

    # Checks 3–7 — per-record validation (all errors collected before reporting)
    seen_skus = {}  # sku -> record number

    for i, product in enumerate(products, start=1):
        if not isinstance(product, dict):
            errors.append(
                f"Record {i}: expected an object, got {type(product).__name__}"
            )
            continue

        sku = product.get("sku", "")
        label = f"Record {i} (SKU: {sku})" if sku else f"Record {i}"

        # Check 3 — Required fields
        for field in sorted(REQUIRED_FIELDS):
            if field not in product:
                errors.append(f"{label}: missing required field '{field}'")

        # Check 4 — No extra fields
        extra = sorted(set(product.keys()) - REQUIRED_FIELDS)
        for field in extra:
            errors.append(
                f"{label}: unexpected field '{field}' — not declared in schema"
            )

        # Check 5 — Duplicate SKUs
        if sku:
            if sku in seen_skus:
                errors.append(
                    f"{label}: duplicate SKU — already seen at record {seen_skus[sku]}"
                )
            else:
                seen_skus[sku] = i

        # Check 6 — Category in allowed set
        if "category" in product:
            cat = product["category"]
            if cat not in ALLOWED_CATEGORIES:
                allowed_str = ", ".join(sorted(ALLOWED_CATEGORIES))
                errors.append(
                    f"{label}: invalid category '{cat}'\n"
                    f"          allowed: {allowed_str}"
                )

        # Check 7 — Field value integrity
        if "price" in product:
            price = product["price"]
            if (
                not isinstance(price, (int, float))
                or isinstance(price, bool)
                or price <= 0
            ):
                errors.append(
                    f"{label}: 'price' must be a number greater than 0, got: {price!r}"
                )

        if "image_url" in product:
            val = product["image_url"]
            if not isinstance(val, str) or not val.startswith("https://"):
                errors.append(
                    f"{label}: 'image_url' must start with https://, got: {val!r}"
                )

        for field in ("sku", "name", "product_url"):
            if field in product:
                val = product[field]
                if not isinstance(val, str) or not val.strip():
                    errors.append(
                        f"{label}: '{field}' must be a non-empty string, got: {val!r}"
                    )

    # Report results
    if errors:
        print(f"\nFAILED — {len(errors)} error(s) found:\n")
        for idx, err in enumerate(errors, start=1):
            print(f"  [{idx}] {err}")
        print("\n  Fix all errors above before running the build.")
        sys.exit(1)
    else:
        print(f"  \u2713 Required fields present ({len(products)} records)")
        print("  \u2713 No extra fields")
        print("  \u2713 No duplicate SKUs")
        print("  \u2713 All categories valid")
        print("  \u2713 Field values valid")
        print(f"\nPASSED — {len(products)} products ready to build.")
        sys.exit(0)


if __name__ == "__main__":
    main()
