import os
import json
import re
import time
import requests
from urllib.parse import quote, unquote, urlparse, urlunparse
from dotenv import load_dotenv


def _fix_mojibake(text: str) -> str:
    """Fix latin-1/utf-8 double-encoding (e.g. 'BrÃ¼Mate' → 'BrüMate').

    Some API responses have string values that were encoded as UTF-8 bytes but
    then decoded as latin-1, resulting in mojibake like 'Ã¼' for 'ü'.
    Re-encoding as latin-1 and decoding as UTF-8 reverses this.
    Returns the original string unchanged if the round-trip fails.
    """
    if not text or not isinstance(text, str):
        return text
    try:
        return text.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text

load_dotenv()


def _encode_url(url):
    """Normalize a URL path: decode any existing percent-encoding then re-encode safely.

    Idempotent — safe on both raw paths (spaces/& literals) and already-encoded paths.
    """
    if not url:
        return url
    try:
        p = urlparse(url)
        return urlunparse(p._replace(path=quote(unquote(p.path), safe="/")))
    except Exception:
        return url


def get_env(name):
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value

def get_token():
    base_url = get_env("WEBSITE_API_URL").rstrip("/")
    url = f"{base_url}/token"

    response = requests.post(
        url,
        headers={"websiteguid": get_env("WEBSITE_GUID")},
        data={
            "Username": get_env("WEBSITE_USERNAME"),
            "Password": get_env("WEBSITE_PASSWORD"),
        },
        timeout=(10, 30),
    )
    response.raise_for_status()

    data = response.json()
    token = data.get("access_token")
    if not token:
        raise RuntimeError(f"No access_token returned. Response: {data}")
    return token

def _find_matching_product(products, sku):
    """Match a SKU against API product results using two field sources and three tests.

    Source A — product-level ``itemNo``
        Used by ETS, AIL, and other third-party supplier products.
        The product has ``itemNo: "ETS80044-G"`` but its variant ``sku.sku``
        values are colour codes (e.g. ``ETS80044-ABC``) that bear no relation
        to the itemNo.  Matching against itemNo lets us find these products.

    Source B — variant-level ``sku[].sku``
        Used by COL-prefix and most HealthMerch-branded products where every
        variant carries the full product SKU (e.g. ``COL9059-PB``).

    For each source the following tests are tried, in order:

    Pass 1 — exact:    value == sku              (e.g. COL50224NE, ETS80044-G)
    Pass 2 — iexact:   value.upper() == sku      (mixed-case variants)
    Pass 3 — prefix:   value.startswith(sku)     (base SKU HPR9055 → HPR9055-WHT)

    Returns (product, sku_obj, match_type) or (None, None, None).
    ``sku_obj`` is the matched variant dict; for itemNo matches it is the first
    available variant (used only for ``variantcolorname`` in clean_product).
    """
    sku_upper = sku.upper()

    for pass_name, test in [
        ("exact",   lambda v: v == sku),
        ("iexact",  lambda v: v.upper() == sku_upper),
        ("prefix",  lambda v: v.upper().startswith(sku_upper)),
    ]:
        for product in products:
            # ── Source A: product-level itemNo (ETS / third-party products) ──
            item_no = product.get("itemNo", "")
            if item_no and test(item_no):
                sku_objs = product.get("sku", [])
                return product, (sku_objs[0] if sku_objs else {}), pass_name + "_itemNo"

            # ── Source B: variant-level sku.sku (COL / branded products) ──
            for sku_obj in product.get("sku", []):
                if test(sku_obj.get("sku", "")):
                    return product, sku_obj, pass_name

    return None, None, None


def _fallback_search_texts(sku: str) -> list:
    """Return alternative SearchText values to try when the full SKU finds nothing.

    The API's SearchText searches product names and descriptions — it does NOT
    index itemNo directly.  Third-party vendor SKUs (ETS, HPR, PCN, …) often
    have no match by their full code, so we progressively simplify:

    Step 1 — strip trailing suffix(es)
        'ETS80044-G'     → 'ETS80044'
        'ETS1600-62BK-G' → 'ETS1600-62BK', then 'ETS1600'

    Step 2 — strip vendor-prefix letters, leaving just the numeric/alphanumeric ID
        'ETS80044'  → '80044'
        'HPR9055'   → '9055'
        'PCN7142'   → '7142'
        'SNZPB23701'→ '23701'

    The numeric ID typically appears in product names/tags and is the last
    reliable search handle before giving up.

    Examples
    --------
    'ETS80044-G'    → ['ETS80044', '80044']
    'HPR9055'       → ['9055']
    'COL9059-PB'    → ['COL9059', '9059']
    'COL50224NE'    → ['50224NE']        (no hyphen, but numeric suffix still tried)
    '720'           → []                 (already pure numeric — original search works)
    """
    seen: set = {sku}
    candidates: list = []

    def _add(s: str) -> None:
        if s and s not in seen:
            seen.add(s)
            candidates.append(s)

    # ── Step 1: strip trailing hyphen-segments ──────────────────────────────
    current = sku
    for _ in range(2):           # at most 2 levels (e.g. '-62BK' then '-G')
        stripped = re.sub(r'-[^-]+$', '', current)
        if not stripped or stripped == current:
            break
        _add(stripped)
        current = stripped

    # ── Step 2: strip leading vendor-prefix letters ─────────────────────────
    # Use the most-stripped version from step 1 as the base, or the original.
    base = candidates[-1] if candidates else sku
    numeric = re.sub(r'^[A-Za-z]+', '', base)
    _add(numeric)

    return candidates


def _api_search(token, search_text, headers_base, retries=3):
    """Execute one API product search and return the raw product list.

    Returns the list of product dicts on success, or None on unrecoverable error.
    Retries up to `retries` times on timeout.
    """
    base_url = get_env("WEBSITE_API_URL").rstrip("/")
    url = f"{base_url}/Products/GetProductsAPI/"

    payload = {
        "Category": "",
        "Colors": "",
        "MaxPrice": 0,
        "MinPrice": 0,
        "PageNo": 1,
        "PageSize": 100,
        "SearchText": search_text,
        "Industry": "",
        "ParentEvents": "",
        "SubCategory": "",
        "WebsiteGuid": get_env("WEBSITE_GUID"),
        "LanguageGuid": get_env("WEBSITE_LANGUAGE_GUID"),
        "ShowViewAll": "true",
        "SortName": "Popularity_desc",
    }

    for attempt in range(1, retries + 1):
        try:
            response = requests.post(
                url,
                headers=headers_base,
                json=payload,
                timeout=(10, 60),
            )
            response.raise_for_status()
            data = json.loads(response.content.decode('utf-8'))
            return data.get("data", {}).get("productlstdata", [])

        except requests.exceptions.ReadTimeout:
            print(f"⏱ Timeout searching '{search_text}' (attempt {attempt}/{retries})")
            time.sleep(2)
        except requests.exceptions.RequestException as exc:
            print(f"❌ Request error for '{search_text}': {exc}")
            return None
        except Exception as exc:
            print(f"❌ Unexpected error for '{search_text}': {exc}")
            return None

    return None


def fetch_by_sku(token, sku, retries=3):
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json;charset=UTF-8",
        "WebsiteGuid": get_env("WEBSITE_GUID"),
        "LanguageGuid": get_env("WEBSITE_LANGUAGE_GUID"),
        "defaultlanguageguid": get_env("WEBSITE_LANGUAGE_GUID"),
        "CurrencyGuid": get_env("WEBSITE_CURRENCY_GUID"),
        "Defaultcurrencyguid": get_env("WEBSITE_CURRENCY_GUID"),
        "Websiteurl": "https://www.healthmerch.com/",
        "isindustries": "true",
        "isskuvm": "true",
    }

    # Build the ordered list of search texts to try: original first, then fallbacks.
    search_texts = [sku] + _fallback_search_texts(sku)

    for search_text in search_texts:
        products = _api_search(token, search_text, headers, retries=retries)

        if products is None:
            # Unrecoverable network/request error — give up entirely
            return None

        product, sku_obj, match_type = _find_matching_product(products, sku)
        if product:
            product["_matched_sku"] = sku
            product["_matched_variant"] = sku_obj
            label = f"{match_type} match" if match_type != "exact" else "exact"
            if search_text != sku or match_type != "exact":
                print(f"  ({label} via search='{search_text}' → variant {sku_obj.get('sku')})")
            return product

    return None

# Matches "{DesignTheme}-{ProductName}" where the prefix is either:
#   - ALL-CAPS (e.g. "NURSE-")
#   - A multi-word phrase (e.g. "Proud & Bold-", "Get Tested-", "All Colors PRIDE-")
# Single-word mixed-case prefixes (e.g. "Non-Woven") are NOT stripped.
# The phrase alternative is non-greedy so it stops at the FIRST hyphen. Greedy,
# it ran to the last one and ate most of the name: "Get Tested-Full Color
# Kan-Tastic" came out as "Tastic", and every "(Full-Color Front Only)" table
# throw came out as "Color Front Only)".
_NAME_PREFIX_RE = re.compile(r'^([A-Z]{2,}|.+? .+?)-(.+)$')


def _clean_name(raw: str) -> str:
    """Strip design-theme prefix (e.g. 'NURSE-', 'Proud & Bold-') from product names."""
    if not raw:
        return raw
    m = _NAME_PREFIX_RE.match(raw)
    if m:
        rest = m.group(2).strip()
        # Fix leading decimal: ".34 Oz." → "0.34 Oz."
        if rest.startswith('.') and len(rest) > 1 and rest[1].isdigit():
            rest = '0' + rest
        return rest
    return raw


def extract_colors(product):
    colors = []
    for sku_obj in product.get("sku", []):
        color = sku_obj.get("variantcolorname")
        if color and color not in colors:
            colors.append(color)
    return colors

def is_complete_product(product):
    has_image = bool(product.get("itemImageURL"))
    has_link = bool(product.get("websiteProductURL"))
    has_price = product.get("priceFrom") not in (None, "", 0, "0")
    has_name = bool(product.get("name"))
    return has_image and has_link and has_price and has_name

def _extract_api_category(raw_cats):
    """Extract (category, subcategory) from the API category list.

    The API returns a list of category objects each with a ``categorytype``.
    The main category is the entry where categorytype == "Category";
    ``parentcategoryname`` is the top-level bucket (e.g. "Wellness", "Bags")
    and ``categorynname`` is the subcategory (e.g. "Sanitizers", "Tote Bags").
    """
    for c in (raw_cats or []):
        if c.get("categorytype") == "Category":
            return (
                c.get("parentcategoryname") or "",
                c.get("categorynname") or "",
            )
    return "", ""


def clean_product(product):
    matched_variant = product.get("_matched_variant", {})
    colors = extract_colors(product)
    api_category, api_subcategory = _extract_api_category(product.get("category", []))

    raw_name = _fix_mojibake(product.get("name", ""))
    raw_desc = _fix_mojibake(
        product.get("shortDescription") or product.get("description") or ""
    )

    return {
        "id": product.get("id"),
        "name": _clean_name(raw_name),
        "sku": product.get("_matched_sku"),
        "price": product.get("priceFrom"),
        "image_url": _encode_url(product.get("itemImageURL")),
        "product_url": product.get("websiteProductURL"),
        "description": raw_desc,
        "colors": colors,
        "matched_color": matched_variant.get("variantcolorname", ""),
        "category": api_category,
        "subcategory": api_subcategory,
    }

def main():
    print("\n🎯 FETCHING PRODUCTS BY SKU")
    print("=" * 70)

    skus = [
        "COL9059-PB",
        "COL3200-GT",
        "COL6962-GT",
        "COL9051-ACP",
        "COLDPSF-691001-AYO",
        "COLLVLFLATPOUCH-BY",
        "COL9055-BB",
        "COL30-EY",
        "COL9043FP",
        "COL56223-PRI-GT",
        "COL8100S-OYP",
        "COLELB-BB-SM",
        "COL3330LJP",
        "COL1035-LIL",
        "COLCLX-LW",
        "COLC16Y-LWA",
        "COLPLB-OV-OSL",
        "COLFBFASUB1-OYP",
        "COL8057-PP",
        "COLC17B-PP",
        "COLCCT10-PF",
    ]

    token = get_token()
    print("✅ Token obtained\n")

    found_products_raw = []
    found_products_clean = []
    incomplete_products = []
    not_found = []

    for index, sku in enumerate(skus, 1):
        print(f"{index}. {sku}...", end=" ")

        product = fetch_by_sku(token, sku)

        if not product:
            not_found.append(sku)
            print("❌ Not found")
            time.sleep(0.5)
            continue

        if not is_complete_product(product):
            incomplete_products.append(
                {
                    "sku": sku,
                    "name": product.get("name"),
                    "has_image": bool(product.get("itemImageURL")),
                    "has_link": bool(product.get("websiteProductURL")),
                    "has_price": product.get("priceFrom") not in (None, "", 0, "0"),
                }
            )
            print("⚠️ Found but incomplete data")
            time.sleep(0.5)
            continue

        found_products_raw.append(product)
        clean = clean_product(product)
        found_products_clean.append(clean)
        print(f"✅ {clean['name']} - ${clean['price']}")

        time.sleep(0.5)

    print(f"\n{'=' * 70}")
    print(f"✅ Found complete products: {len(found_products_clean)}")
    print(f"⚠️ Found but incomplete: {len(incomplete_products)}")
    print(f"❌ Not found: {len(not_found)}")
    print(f"{'=' * 70}\n")

    if not_found:
        print("SKUs not found:")
        for sku in not_found:
            print(f"  • {sku}")
        print()

    if incomplete_products:
        print("Incomplete products:")
        for item in incomplete_products:
            print(
                f"  • {item['sku']} | {item['name']} | "
                f"image={item['has_image']} link={item['has_link']} price={item['has_price']}"
            )
        print()

    os.makedirs("output/data", exist_ok=True)

    with open("output/data/products_by_sku_raw.json", "w", encoding="utf-8") as f:
        json.dump(found_products_raw, f, indent=2, ensure_ascii=False)

    with open("output/data/products_by_sku_clean.json", "w", encoding="utf-8") as f:
        json.dump(found_products_clean, f, indent=2, ensure_ascii=False)

    print("💾 Saved raw file to: output/data/products_by_sku_raw.json")
    print("💾 Saved clean file to: output/data/products_by_sku_clean.json")

    if found_products_clean:
        print("\n📋 PRODUCT DETAILS:\n")
        for product in found_products_clean:
            print(product["name"])
            print(f"  SKU: {product['sku']}")
            print(f"  Price: ${product['price']}")
            print(f"  Image: {'✅' if product['image_url'] else '❌'}")
            print(f"  Link: {'✅' if product['product_url'] else '❌'}")
            print(f"  Colors: {', '.join(product['colors'][:5]) if product['colors'] else 'N/A'}")
            print()

    print("🎨 Ready to build lookbook with these products!")

if __name__ == "__main__":
    main()
