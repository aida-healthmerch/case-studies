#!/usr/bin/env python3
"""
build.py — HealthMerch Lookbook Build Script

Reads data/{slug}.json and generates output/{slug}.html.
Run from the repo root after validate.py passes:

    python scripts/validate.py && python scripts/build.py --slug nurses-week-26

Input:  data/{slug}.json         (canonical schema — required)
        data/{slug}-config.json  (campaign config — optional)
Output: output/{slug}.html       (complete static HTML lookbook)
"""
import argparse
import html
import json
import os
import sys
from collections import defaultdict
from urllib.parse import quote, unquote, urlparse, urlunparse

BASE_URL = "https://www.healthmerch.com"
HM_LOGO_URL = "https://677757.fs1.hubspotusercontent-na1.net/hubfs/677757/healthmerch-logo.png"
HM_LOGO_WHITE_URL = "https://677757.fs1.hubspotusercontent-na1.net/hubfs/677757/healthmerch-logo-white.png"

_PRODUCT_PLACEHOLDER = (
    "data:image/svg+xml,%3Csvg%20xmlns%3D%22http%3A%2F%2Fwww.w3.org%2F2000%2Fsvg%22"
    "%20width%3D%22300%22%20height%3D%22300%22%3E"
    "%3Crect%20fill%3D%22%23eef3f9%22%20width%3D%22300%22%20height%3D%22300%22%2F%3E"
    "%3C%2Fsvg%3E"
)

def _encode_url(url):
    """Normalize a URL path: decode any existing percent-encoding then re-encode safely.

    This is idempotent — safe to call on both raw paths (spaces/& literals) and
    already-encoded paths (won't double-encode).
    """
    if not url:
        return url
    try:
        p = urlparse(url)
        return urlunparse(p._replace(path=quote(unquote(p.path), safe="/")))
    except Exception:
        return url


CATEGORY_DISPLAY = {
    "Apparel":         "Personalized Apparel",
    "Bags":            "Personalized Bags",
    "Drinkware":       "Personalized Drinkware",
    "Wellness":        "Personalized Wellness",
    "Technology":      "Personalized Technology",
    "Office Supplies": "Personalized Office Supplies",
    "Outdoor":         "Personalized Outdoor",
    "Stickers":        "Personalized Stickers",
    "Other":           "Featured Products",
}

_STANDARD_CATEGORIES = {
    "Apparel", "Bags", "Drinkware", "Wellness",
    "Technology", "Office Supplies", "Outdoor", "Stickers", "Other",
}

CATEGORY_ORDER = [
    "Apparel", "Bags", "Drinkware", "Wellness",
    "Technology", "Office Supplies", "Outdoor", "Stickers",
]

CATEGORY_CTAS = {}
CATEGORY_BANDS = set()

CATEGORY_DESCRIPTIONS = {
    "Personalized Apparel":
        "Wearable recognition that shows your team and community you care.",
    "Personalized Bags":
        "Practical branded bags for events, outreach, and everyday community touchpoints.",
    "Personalized Drinkware":
        "Keep your mission top of mind with every sip.",
    "Personalized Wellness":
        "Purpose-driven wellness items that promote health and show you care.",
    "Personalized Technology":
        "Useful tech accessories that keep your brand in hand every day.",
    "Personalized Office Supplies":
        "Mission-aligned desk essentials that reinforce your brand daily.",
    "Personalized Outdoor":
        "Durable event gear built for community outreach and health campaigns.",
    "Personalized Stickers":
        "High-visibility stickers for health campaigns, events, and community awareness.",
    "Featured Products":
        "Curated promotional products aligned with your mission and audience.",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_config(config_file):
    if not os.path.isfile(config_file):
        print(f"  Note: {config_file} not found — using built-in defaults.")
        return {}
    with open(config_file, "r", encoding="utf-8") as f:
        return json.load(f)


def load_theme_css(slug):
    """Append data/{slug}-theme.css after the base stylesheet, if present.

    Lets one campaign restyle itself without touching the shared CSS every other
    lookbook renders from. Returns an empty string when the campaign has no theme.
    """
    path = os.path.join("data", f"{slug}-theme.css")
    if not os.path.isfile(path):
        return ""
    with open(path, encoding="utf-8") as f:
        css = f.read()
    print(f"  Applying campaign theme from {path} ({len(css)} chars).")
    return "\n\n/* ---- campaign theme ---- */\n" + css


def load_collections(slug):
    """Load data/{slug}-collections.json, the campaign's design collections.

    Returns {} when the campaign has none, which is every lookbook that does not
    carry artwork collections. A collection with no resolved products is dropped
    here too: scripts/fetch_nurse_collections.py already fails the run on one, so
    reaching this point means the file was hand-edited, and a card with nothing
    behind it is worse than no card.
    """
    path = os.path.join("data", f"{slug}-collections.json")
    if not os.path.isfile(path):
        return {}
    with open(path, encoding="utf-8") as f:
        doc = json.load(f)

    ready, skipped = [], []
    for collection in doc.get("collections") or []:
        if collection.get("products") and collection.get("name"):
            ready.append(collection)
        else:
            skipped.append(collection.get("code") or collection.get("slug") or "?")
    doc["collections"] = ready

    if skipped:
        print(f"  Warning: collections with no products or no name were dropped: {', '.join(skipped)}")
    if ready:
        total = sum(len(c["products"]) for c in ready)
        print(f"  Collections: {len(ready)} designs, {total} products.")
    return doc if ready else {}


def apply_custom_sections(config):
    """Register campaign-only product sections from config["custom_sections"].

    Each entry is {"key", "label", "description"}. The key is the value a product
    carries in its "category" field; the label is the heading rendered. Custom
    sections lead the page, ahead of the standard categories. Campaigns without
    the setting are unaffected.
    """
    sections = config.get("custom_sections") or []
    keys = []
    for section in sections:
        key = (section.get("key") or "").strip()
        label = (section.get("label") or key).strip()
        if not key:
            continue
        CATEGORY_DISPLAY[key] = label
        CATEGORY_DESCRIPTIONS[label] = (section.get("description") or "").strip()

        note = (section.get("cta_note") or "").strip()
        if note:
            CATEGORY_CTAS[label] = {
                "note": note,
                "label": (section.get("cta_label") or "Schedule a Call").strip(),
                "url": (section.get("cta_url") or "").strip(),
            }
        if section.get("band"):
            CATEGORY_BANDS.add(label)
        keys.append(key)

    if keys:
        # Lead with the custom sections, then the standard order.
        CATEGORY_ORDER[:] = keys + [c for c in CATEGORY_ORDER if c not in keys]
        print(f"  Custom sections: {', '.join(CATEGORY_DISPLAY[k] for k in keys)}")
    return keys


def build_full_url(product_url):
    if not product_url:
        return BASE_URL
    if not product_url.startswith("http"):
        return f"{BASE_URL}/{product_url}"
    return product_url


def assign_tag(price, event_label=""):
    """Return (css_class, label) for a product tag based on price."""
    if price < 5:
        return "tag-giveaway", "Giveaway Pick"
    return "tag-primary", (event_label if event_label else "Staff Pick")


# ---------------------------------------------------------------------------
# CSS
# ---------------------------------------------------------------------------

_COLLECTIONS_CSS = """/* ── DESIGN COLLECTIONS ──
   Sits under the whole product grid. One card per artwork, each opening a panel
   of the products that artwork prints on, so a blank shared by six collections
   is shown once per collection rather than six times in a row. */
.collections{background:var(--hm-bg-soft);border-top:1px solid var(--hm-line);padding:4rem 1.5rem;scroll-margin-top:114px}
.collections-inner{max-width:1200px;margin:0 auto}
.collections .cat-header{text-align:center;margin-bottom:2.25rem}
.collections .cat-header h2{font-size:clamp(1.5rem,3vw,2.1rem);font-weight:800;color:var(--hm-navy-800);margin-bottom:.6rem}
.collections .cat-header p{font-size:.95rem;color:var(--hm-slate);line-height:1.7;max-width:62ch;margin:0 auto}
.coll-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:1.25rem}
.coll-card{display:flex;flex-direction:column;width:100%;text-align:left;padding:0;background:#fff;border:1px solid var(--hm-line);border-radius:var(--radius-lg);overflow:hidden;box-shadow:var(--shadow-sm);cursor:pointer;font:inherit;color:inherit;transition:border-color .2s,box-shadow .2s,transform .2s}
.coll-card:hover{border-color:var(--hm-navy-300);box-shadow:var(--shadow-md);transform:translateY(-2px)}
.coll-card:focus-visible{outline:3px solid var(--hm-sky-600);outline-offset:2px}
.coll-card[aria-expanded="true"]{border-color:var(--hm-navy-700);box-shadow:var(--shadow-md)}
.coll-cover{background:var(--hm-bg-soft);aspect-ratio:1;overflow:hidden}
.coll-cover img{width:100%;height:100%;object-fit:cover}
.coll-body{padding:1rem 1.1rem 1.15rem;display:flex;flex-direction:column;gap:.4rem;flex:1}
.coll-name{font-size:1rem;font-weight:800;color:var(--hm-navy-800);line-height:1.3}
.coll-kicker{font-size:.85rem;color:var(--hm-slate);line-height:1.55}
.coll-count{margin-top:auto;padding-top:.5rem;font-size:.75rem;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:var(--hm-navy-600)}
/* The nav (60px) and the filter bar (~53px) are both sticky, so a panel scrolled
   to the top of the viewport would open with its heading underneath them. */
.coll-panel{margin-top:1.5rem;background:#fff;border:1px solid var(--hm-line);border-radius:var(--radius-lg);padding:1.75rem 1.5rem;scroll-margin-top:128px}
.coll-panel[hidden]{display:none}
.coll-panel-top{display:flex;align-items:baseline;justify-content:space-between;gap:1rem;flex-wrap:wrap;margin-bottom:1.25rem;padding-bottom:1rem;border-bottom:1px solid var(--hm-line-soft)}
.coll-panel-title{font-size:1.15rem;font-weight:800;color:var(--hm-navy-800)}
.coll-panel-note{font-size:.85rem;color:var(--hm-slate)}
.coll-close{background:none;border:1.5px solid var(--hm-navy-200);color:var(--hm-navy-700);border-radius:var(--radius-sm);padding:.35rem .9rem;font:inherit;font-size:.8rem;font-weight:700;cursor:pointer;transition:border-color .2s,background .2s}
.coll-close:hover{border-color:var(--hm-navy-700);background:var(--hm-navy-50)}
@media(max-width:520px){.coll-grid{grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:.9rem}.collections{padding:3rem 1rem}.coll-panel{padding:1.25rem 1rem}}

"""


def render_css(with_collections=True):
    # Plain string — not an f-string. Braces are literal CSS.
    return """\
:root {
  --hm-navy-900: #081a2e; --hm-navy-800: #0d2440; --hm-navy-700: #143256;
  --hm-navy-600: #1f4477; --hm-navy-500: #2c5a99; --hm-navy-400: #5079b3;
  --hm-navy-300: #859fc9; --hm-navy-200: #b8c8df; --hm-navy-100: #dde6f1;
  --hm-navy-50: #eef3f9;
  --hm-sky-700: #3aa3da; --hm-sky-600: #61c5f7; --hm-sky-500: #82d2f9;
  --hm-sky-100: #ecf7fe;
  --hm-coral-500: #ea8474; --hm-green-500: #6cb084;
  --hm-ink: #0d1626; --hm-graphite: #353e5c; --hm-slate: #5a6478;
  --hm-mist: #8a92a3; --hm-line: #e3e6ec; --hm-line-soft: #eef0f4;
  --hm-bg: #ffffff; --hm-bg-soft: #f5f7fb;
  --radius-sm: 6px; --radius-md: 12px; --radius-lg: 20px;
  /* The footer was written against a design-system stylesheet that is not
     included here, so these resolved to nothing: max-width fell back to none
     and padding to 0, which is why the footer ran edge to edge while every
     other section was inset. Values match the rest of the page. */
  --container-wide: 1200px; --gutter: 1.5rem;
  --fs-12: .75rem; --fs-14: .875rem;
  --fw-bold: 700; --tracking-wider: .04em;
  --shadow-sm: 0 1px 3px rgba(13,36,64,.08);
  --shadow-md: 0 4px 16px rgba(13,36,64,.12);
  --shadow-lg: 0 12px 40px rgba(13,36,64,.16);
}
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
html{scroll-behavior:smooth}
body{font-family:'Nunito Sans',system-ui,sans-serif;background:var(--hm-bg);color:var(--hm-ink);line-height:1.6;-webkit-font-smoothing:antialiased}
img{display:block;max-width:100%}
a{color:inherit;text-decoration:none}

/* ── NAV ── */
.site-nav{position:sticky;top:0;z-index:100;background:rgba(255,255,255,.92);backdrop-filter:blur(12px);border-bottom:1px solid var(--hm-line);padding:0 1.5rem}
.nav-inner{max-width:1200px;margin:0 auto;display:flex;align-items:center;gap:1rem;height:60px}
.nav-logo img{height:28px;width:auto}
.nav-links{display:flex;gap:0.25rem;margin-left:auto}
.nav-links a{font-size:.8rem;font-weight:600;color:var(--hm-slate);padding:.35rem .7rem;border-radius:var(--radius-sm);transition:color .15s,background .15s}
.nav-links a:hover{color:var(--hm-navy-700);background:var(--hm-navy-50)}
.nav-ctas{display:flex;gap:.5rem;margin-left:.75rem}
.btn--sm{display:inline-flex;align-items:center;gap:.35rem;padding:.4rem 1rem;border-radius:var(--radius-sm);font-size:.8rem;font-weight:700;white-space:nowrap;transition:all .2s}
.btn--outline{border:1.5px solid var(--hm-navy-200);color:var(--hm-navy-700)}
.btn--outline:hover{border-color:var(--hm-navy-700);background:var(--hm-navy-50)}
.btn--primary{background:var(--hm-navy-700);color:#fff}
.btn--primary:hover{background:var(--hm-navy-800)}
@media(max-width:640px){.nav-links,.btn--outline{display:none}}

/* ── HERO ── */
.hero{background:linear-gradient(140deg,var(--hm-navy-700) 0%,var(--hm-navy-800) 60%,var(--hm-navy-900) 100%);padding:4rem 1.5rem 3rem}
.hero-inner{max-width:1200px;margin:0 auto;display:grid;grid-template-columns:1fr 420px;gap:3rem;align-items:center}
.hero-eyebrow{display:inline-block;font-size:.7rem;font-weight:800;letter-spacing:.12em;text-transform:uppercase;color:var(--hm-sky-600);background:rgba(97,197,247,.12);border:1px solid rgba(97,197,247,.3);border-radius:100px;padding:.3rem .85rem;margin-bottom:1.25rem}
.hero h1{font-size:clamp(1.9rem,4vw,2.9rem);font-weight:800;color:#fff;line-height:1.15;margin-bottom:1rem}
.hero-intro{font-size:1rem;color:var(--hm-navy-200);line-height:1.7;margin-bottom:1.75rem;max-width:520px}
.hero-actions{display:flex;gap:.75rem;flex-wrap:wrap}
.btn--hero{display:inline-flex;align-items:center;gap:.5rem;padding:.75rem 1.5rem;border-radius:var(--radius-md);font-size:.9rem;font-weight:700;transition:all .2s}
.btn--hero-primary{background:var(--hm-sky-600);color:var(--hm-navy-900)}
.btn--hero-primary:hover{background:var(--hm-sky-500);transform:translateY(-1px)}
.btn--hero-ghost{border:1.5px solid rgba(255,255,255,.3);color:#fff}
.btn--hero-ghost:hover{background:rgba(255,255,255,.08)}
.hero-visual{position:relative}
.hero-img{width:100%;height:320px;object-fit:cover;border-radius:var(--radius-lg);box-shadow:var(--shadow-lg)}
.hero-logo-pill{position:absolute;bottom:-16px;left:50%;transform:translateX(-50%);background:#fff;border-radius:100px;padding:.5rem 1.25rem;box-shadow:var(--shadow-md);display:flex;align-items:center}
.hero-logo-pill img{height:22px;width:auto}
@media(max-width:900px){
  .hero-inner{grid-template-columns:1fr}
  .hero-visual{display:none}
}

/* ── FILTER BAR ── */
.filter-bar{position:sticky;top:60px;z-index:90;background:var(--hm-bg);border-bottom:1px solid var(--hm-line);padding:0 1.5rem}
.filter-inner{max-width:1200px;margin:0 auto;display:flex;gap:.375rem;padding:.625rem 0;overflow-x:auto;scrollbar-width:none}
.filter-inner::-webkit-scrollbar{display:none}
.filter-btn{white-space:nowrap;flex-shrink:0;padding:.4rem 1rem;border-radius:100px;font-size:.78rem;font-weight:700;border:1.5px solid var(--hm-line);background:transparent;color:var(--hm-slate);cursor:pointer;transition:all .2s;font-family:inherit}
.filter-btn:hover{border-color:var(--hm-navy-300);color:var(--hm-navy-700)}
.filter-btn.active{background:var(--hm-navy-700);border-color:var(--hm-navy-700);color:#fff}

/* ── PRODUCTS ── */
.products-wrap{max-width:1200px;margin:0 auto;padding:2.5rem 1.5rem 4rem}
.category-section{margin-bottom:3rem}
.image-band{margin:3rem 0;border-radius:var(--radius-lg);overflow:hidden;background:var(--hm-bg-soft)}
.image-band-figure{margin:0}
.image-band-frame{position:relative;width:100%;aspect-ratio:21/9;overflow:hidden;background:var(--hm-bg-soft)}
.image-band-frame img{width:100%;height:100%;object-fit:cover;display:block}
.image-band figcaption{padding:.85rem 1.25rem;font-size:.85rem;color:var(--hm-slate);background:var(--hm-bg);border-top:1px solid var(--hm-line)}
@media (max-width:640px){.image-band-frame{aspect-ratio:4/3}.image-band{margin:2rem 0}}
.section-cta{margin-top:1.5rem;padding:1.25rem 1.5rem;border:1px solid var(--hm-line);border-left:4px solid var(--hm-sky-600);border-radius:var(--radius-md);background:var(--hm-bg-soft);display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:1rem}
.section-cta p{margin:0;font-size:.9rem;color:var(--hm-graphite);max-width:64ch}
.section-cta a{flex-shrink:0;padding:.6rem 1.25rem;border-radius:var(--radius-sm);background:var(--hm-navy-700);color:#fff;font-size:.82rem;font-weight:700;white-space:nowrap}
.cat-header{margin-bottom:1.5rem;padding-bottom:1rem;border-bottom:1px solid var(--hm-line)}
.cat-header h2{font-size:1.35rem;font-weight:800;color:var(--hm-navy-700);margin-bottom:.25rem}
.cat-header p{font-size:.875rem;color:var(--hm-slate)}
.product-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:1.25rem}
.product-card{background:var(--hm-bg);border:1px solid var(--hm-line);border-radius:var(--radius-md);overflow:hidden;display:flex;flex-direction:column;transition:box-shadow .2s,transform .2s}
.product-card:hover{box-shadow:var(--shadow-md);transform:translateY(-2px)}
.product-image-wrapper{background:var(--hm-bg-soft);aspect-ratio:1;overflow:hidden}
.product-image{width:100%;height:100%;object-fit:cover;transition:transform .3s}
.product-card:hover .product-image{transform:scale(1.04)}
.product-info{padding:1rem;display:flex;flex-direction:column;flex:1;gap:.5rem}
.product-tags{display:flex;flex-wrap:wrap;gap:.35rem}
.tag{font-size:.65rem;font-weight:700;letter-spacing:.06em;text-transform:uppercase;padding:.2rem .55rem;border-radius:100px}
.tag-primary{background:var(--hm-navy-50);color:var(--hm-navy-600)}
.tag-giveaway{background:#fef3e2;color:#b45309}
.product-name{font-size:.9rem;font-weight:700;color:var(--hm-ink);line-height:1.35;flex:1}
.product-price{font-size:1rem;font-weight:800;color:var(--hm-navy-700)}
.shop-now-btn{display:inline-flex;align-items:center;gap:.3rem;margin-top:.75rem;padding:.5rem 1rem;background:var(--hm-navy-700);color:#fff;border-radius:var(--radius-sm);font-size:.78rem;font-weight:700;transition:background .2s;align-self:flex-start}
.shop-now-btn::after{content:'→'}
.shop-now-btn:hover{background:var(--hm-navy-800)}

/* ── AUDIENCE CTA ── */
.audience{background:linear-gradient(140deg,var(--hm-navy-700) 0%,var(--hm-navy-900) 100%);padding:4rem 1.5rem}
.audience-inner{max-width:1200px;margin:0 auto;display:grid;grid-template-columns:1fr 1fr;gap:3rem;align-items:start}
.audience h2{font-size:clamp(1.5rem,3vw,2.2rem);font-weight:800;color:#fff;margin-bottom:1rem;line-height:1.2}
.audience p{font-size:.95rem;color:var(--hm-navy-200);line-height:1.7;margin-bottom:1.75rem}
.audience-cta{display:inline-flex;align-items:center;gap:.5rem;padding:.8rem 1.6rem;background:var(--hm-sky-600);color:var(--hm-navy-900);border-radius:var(--radius-md);font-weight:800;font-size:.9rem;transition:all .2s}
.audience-cta:hover{background:var(--hm-sky-500);transform:translateY(-1px)}
.audience-list{list-style:none;display:grid;grid-template-columns:1fr 1fr;gap:.5rem .75rem}
.audience-list li{font-size:.85rem;color:var(--hm-navy-200);display:flex;align-items:center;gap:.5rem}
.audience-list li::before{content:'';width:6px;height:6px;border-radius:50%;background:var(--hm-sky-600);flex-shrink:0}
@media(max-width:768px){.audience-inner{grid-template-columns:1fr}.audience-list{grid-template-columns:1fr}}

/* ── FOOTER ── */
.hm-footer{background:var(--hm-navy-900);color:rgba(255,255,255,0.78);padding:80px 0 32px;}
.footer__inner{max-width:var(--container-wide);margin:0 auto;padding:0 var(--gutter);display:grid;grid-template-columns:1.4fr repeat(3,1fr);gap:48px;}
@media(max-width:760px){.footer__inner{grid-template-columns:1fr 1fr;}}
@media(max-width:460px){.footer__inner{grid-template-columns:1fr;}}
.hm-footer h5{margin:0 0 16px;font-size:var(--fs-12);text-transform:uppercase;letter-spacing:var(--tracking-wider);color:rgba(255,255,255,0.5);font-weight:var(--fw-bold);}
.hm-footer ul{list-style:none;padding:0;margin:0;display:flex;flex-direction:column;gap:10px;}
.hm-footer a{color:rgba(255,255,255,0.78);font-size:var(--fs-14);}
.hm-footer a:hover{color:#fff;}
.hm-footer .brand img{height:32px;margin-bottom:16px;background:#fff;border-radius:6px;padding:4px 10px;}
.hm-footer .brand p{font-size:var(--fs-14);line-height:1.6;max-width:32ch;margin:0;}
.footer__bottom{max-width:var(--container-wide);margin:64px auto 0;padding:24px var(--gutter) 0;border-top:1px solid rgba(255,255,255,0.10);display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:16px;font-size:var(--fs-12);color:rgba(255,255,255,0.5);}

/* ── MOBILE STICKY CTA ── */
.sticky-cta{display:none;position:fixed;bottom:0;left:0;right:0;z-index:200;background:var(--hm-navy-900);border-top:1px solid rgba(255,255,255,.1);padding:.75rem 1rem;align-items:center;justify-content:space-between;gap:.75rem}
.sticky-cta a{flex:1;text-align:center;padding:.7rem;background:var(--hm-sky-600);color:var(--hm-navy-900);border-radius:var(--radius-sm);font-weight:800;font-size:.85rem}
.sticky-cta-dismiss{background:none;border:none;color:var(--hm-navy-300);font-size:1.2rem;cursor:pointer;padding:.25rem;line-height:1}
@media(max-width:640px){.sticky-cta{display:flex}}

/* ── MERCH OF THE WEEK ── */
.motw{padding:2rem 1.5rem 0}
.motw-inner{max-width:1200px;margin:0 auto}
.motw-card{display:grid;grid-template-columns:340px 1fr;border-radius:var(--radius-lg);overflow:hidden;border:1px solid var(--hm-line);box-shadow:var(--shadow-md);background:#fff}
.motw-img-wrap{background:var(--hm-bg-soft);aspect-ratio:1;overflow:hidden}
.motw-img-wrap img{width:100%;height:100%;object-fit:cover;transition:transform .4s}
.motw-card:hover .motw-img-wrap img{transform:scale(1.04)}
.motw-body{padding:2.5rem;display:flex;flex-direction:column;justify-content:center;gap:1.25rem;background:linear-gradient(140deg,var(--hm-navy-700) 0%,var(--hm-navy-900) 100%);color:#fff}
.motw-eyebrow{display:inline-flex;align-items:center;gap:.5rem;font-size:.65rem;font-weight:800;letter-spacing:.14em;text-transform:uppercase;color:var(--hm-sky-400)}
.motw-eyebrow::before{content:'';width:6px;height:6px;border-radius:50%;background:var(--hm-sky-500)}
.motw-name{font-size:clamp(1.2rem,2.5vw,1.75rem);font-weight:800;line-height:1.2;color:#fff}
.motw-price{font-size:1.5rem;font-weight:800;color:var(--hm-sky-400)}
.motw-cta{display:inline-flex;align-items:center;gap:.5rem;padding:.75rem 1.5rem;background:var(--hm-sky-600);color:var(--hm-navy-900);border-radius:var(--radius-md);font-weight:800;font-size:.9rem;transition:all .2s;align-self:flex-start}
.motw-cta:hover{background:var(--hm-sky-500);transform:translateY(-1px)}
.motw-cta::after{content:'→'}
@media(max-width:768px){.motw-card{grid-template-columns:1fr}.motw-img-wrap{aspect-ratio:16/9}}

__COLLECTIONS_CSS__/* ── REVEAL ── */
.reveal{opacity:0;transform:translateY(18px);transition:opacity .45s ease,transform .45s ease}
.reveal.visible{opacity:1;transform:none}""".replace(
        "__COLLECTIONS_CSS__", _COLLECTIONS_CSS if with_collections else "")


# ---------------------------------------------------------------------------
# HTML renderers
# ---------------------------------------------------------------------------

def render_head(config, slug):
    page_title = config.get("page_title", slug)
    return f"""\
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width,initial-scale=1" />
<title>{page_title} | HealthMerch</title>
<meta name="description" content="{page_title} — promotional products lookbook from HealthMerch." />
<link rel="icon" type="image/png" href="/favicon.png">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Nunito+Sans:ital,opsz,wght@0,6..12,300;0,6..12,400;0,6..12,500;0,6..12,600;0,6..12,700;0,6..12,800;0,6..12,900;1,6..12,400;1,6..12,600&display=swap" rel="stylesheet">
<script type="text/javascript" id="hs-script-loader" async defer src="//js.hs-scripts.com/677757.js"></script>"""


def render_nav(config):
    # A dark campaign theme needs the reversed logo, or the mark disappears
    # into the nav. Campaigns set nav_logo_url; everyone else keeps the default.
    logo_url = (config.get("nav_logo_url") or "").strip() or HM_LOGO_URL
    cta_label = config.get("cta_label", "Schedule a Call")
    cta_url = config.get("cta_url", "https://meetings.hubspot.com/healthmerch/healthmerch-team-meeting")
    return f"""\
<nav class="site-nav">
  <div class="nav-inner">
    <a class="nav-logo" href="/">
      <img src="{logo_url}" alt="HealthMerch" onerror="this.style.display='none'">
    </a>
    <div class="nav-links">
      <a href="/">All lookbooks</a>
      <a href="https://www.healthmerch.com/products" target="_blank" rel="noopener">Shop all products</a>
    </div>
    <div class="nav-ctas">
      <a href="{cta_url}" class="btn--sm btn--primary" target="_blank" rel="noopener">{cta_label}</a>
    </div>
  </div>
</nav>"""


def render_hero(config):
    eyebrow    = config.get("eyebrow", "")
    page_title = config.get("page_title", "")
    intro_copy = config.get("intro_copy", "").strip()
    cta_label  = config.get("cta_label", "Schedule a Call")
    cta_url    = config.get("cta_url", "https://meetings.hubspot.com/healthmerch/healthmerch-team-meeting")
    hero_url   = config.get("hero_image_url", "").strip()
    logo_url   = config.get("healthmerch_logo_url", "").strip() or HM_LOGO_URL

    if intro_copy:
        words = intro_copy.split()
        if len(words) > 60:
            intro_copy = " ".join(words[:60]).rstrip(".,;:") + "."

    # "stacked" centres the copy and drops a full-bleed image beneath it, so a
    # photograph shot on black runs into the band with no visible edge.
    shop_label = config.get("shop_label", "Browse Products")

    if config.get("hero_layout") == "stacked":
        feature = ""
        if hero_url:
            feature = f"""
    <div class="hero-feature">
      <img src="{_encode_url(hero_url)}" alt="{config.get('hero_alt', eyebrow)}" loading="eager" decoding="async">
    </div>"""
        return f"""\
<section class="hero hero--stacked">
  <div class="hero-inner">
    <div class="hero-copy">
      <span class="hero-eyebrow">{eyebrow}</span>
      <h1>{page_title}</h1>
      <p class="hero-intro">{intro_copy}</p>
      <div class="hero-actions">
        <a href="#products" class="btn--hero btn--hero-primary">{shop_label}</a>
        <a href="{cta_url}" class="btn--hero btn--hero-ghost" target="_blank" rel="noopener">{cta_label}</a>
      </div>
    </div>{feature}
  </div>
</section>"""

    if hero_url:
        visual_html = f"""\
    <div class="hero-visual">
      <img src="{hero_url}" alt="{eyebrow}" class="hero-img" onerror="this.style.display='none'">
      <div class="hero-logo-pill">
        <img src="{logo_url}" alt="HealthMerch" onerror="this.src='{HM_LOGO_URL}'">
      </div>
    </div>"""
    else:
        visual_html = ""

    return f"""\
<section class="hero">
  <div class="hero-inner">
    <div class="hero-copy">
      <span class="hero-eyebrow">{eyebrow}</span>
      <h1>{page_title}</h1>
      <p class="hero-intro">{intro_copy}</p>
      <div class="hero-actions">
        <a href="{cta_url}" class="btn--hero btn--hero-primary" target="_blank" rel="noopener">{cta_label}</a>
        <a href="#products" class="btn--hero btn--hero-ghost">{shop_label}</a>
      </div>
    </div>
{visual_html}
  </div>
</section>"""


def render_motw(product):
    """Render the Merch of the Week featured banner for a single product."""
    name      = product["name"]
    price     = product["price"]
    image_url = _encode_url(product.get("image_url") or "") or _PRODUCT_PLACEHOLDER
    full_url  = build_full_url(product["product_url"])
    name_attr = name.replace('"', "&quot;")
    return f"""\
<div class="motw reveal">
  <div class="motw-inner">
    <div class="motw-card">
      <div class="motw-img-wrap">
        <img src="{image_url}" alt="{name_attr}" loading="eager" decoding="async" onerror="this.onerror=null;this.src='{_PRODUCT_PLACEHOLDER}'">
      </div>
      <div class="motw-body">
        <span class="motw-eyebrow">Merch of the Week</span>
        <div class="motw-name">{name}</div>
        <div class="motw-price">${price:.2f}</div>
        <a href="{full_url}" class="motw-cta" target="_blank" rel="noopener noreferrer">Shop Now</a>
      </div>
    </div>
  </div>
</div>"""


def render_filter_nav(populated_display_names, with_collections=False):
    buttons = ['    <button class="filter-btn active" data-category="all">All Products</button>']
    for display_name in populated_display_names:
        cat_id = display_name.lower().replace(" ", "-")
        label  = display_name.replace("Personalized ", "")
        buttons.append(
            f'    <button class="filter-btn" data-category="{cat_id}">{label}</button>'
        )
    # The designs are a section of the page like any other, so they belong in the
    # same menu. They sit outside .products-wrap, so the filter script singles
    # this one out rather than matching it against a product category.
    if with_collections:
        buttons.append(
            '    <button class="filter-btn" data-category="collections">Collections</button>'
        )
    buttons_html = "\n".join(buttons)
    return f"""\
<nav class="filter-bar" id="products">
  <div class="filter-inner">
{buttons_html}
  </div>
</nav>"""


def render_product_card(product, event_label=""):
    name      = product["name"]
    price     = product["price"]
    image_url = _encode_url(product.get("image_url") or "") or _PRODUCT_PLACEHOLDER
    full_url  = build_full_url(product["product_url"])
    tag_class, tag_label = assign_tag(price, event_label)
    name_attr = name.replace('"', "&quot;")

    return f"""\
      <div class="product-card">
        <div class="product-image-wrapper"><img src="{image_url}" alt="{name_attr}" class="product-image" loading="lazy" decoding="async" onerror="this.onerror=null;this.src='{_PRODUCT_PLACEHOLDER}'"></div>
        <div class="product-info">
          <div class="product-tags"><span class="tag {tag_class}">{tag_label}</span></div>
          <h3 class="product-name">{name}</h3>
          <div class="product-price">${price:.2f}</div>
          <a href="{full_url}" class="shop-now-btn" target="_blank" rel="noopener noreferrer">Shop Now</a>
        </div>
      </div>"""


def render_image_band(band):
    """Render one full-bleed campaign image.

    Sizing sits on the wrapper divs rather than the <img>, because platform CSS
    resets styles on img elements. A band with no src renders nothing, so slots
    can be declared before the artwork exists.
    """
    src_url = (band.get("src") or "").strip()
    if not src_url:
        return ""

    alt = (band.get("alt") or "").replace('"', "&quot;")
    caption = (band.get("caption") or "").strip()
    caption_html = f"\n      <figcaption>{caption}</figcaption>" if caption else ""

    # Match the frame to the artwork so nothing important gets cropped away.
    ratio = (band.get("ratio") or "21/9").strip()
    style = f' style="aspect-ratio:{ratio}"'

    return f"""  <div class="image-band reveal">
    <figure class="image-band-figure">
      <div class="image-band-frame"{style}>
        <img src="{_encode_url(src_url)}" alt="{alt}" loading="lazy" decoding="async">
      </div>{caption_html}
    </figure>
  </div>"""


def render_category_section(display_name, products, event_label="", band_html="", feature=False, band=False):
    cat_id      = display_name.lower().replace(" ", "-")
    feature_cls = " feature-section" if feature else ""
    if band:
        feature_cls += " feature-band"
    description = CATEGORY_DESCRIPTIONS.get(display_name, "")
    cards       = "\n".join(render_product_card(p, event_label) for p in products)

    cta_cfg = CATEGORY_CTAS.get(display_name)
    cta = ""
    if cta_cfg and cta_cfg["url"]:
        cta = f"""    <div class="section-cta">
      <p>{cta_cfg["note"]}</p>
      <a href="{cta_cfg["url"]}" target="_blank" rel="noopener">{cta_cfg["label"]} &#8594;</a>
    </div>"""
    header = f"""    <div class="cat-header">
      <h2>{display_name}</h2>
      <p>{description}</p>
    </div>"""

    # A banded section runs its heading and photograph full-bleed on black,
    # matching the hero, with the products on white underneath.
    if band:
        head_block = f"""    <div class="section-band">
      <div class="section-band-inner">
{header}
{band_html}
      </div>
    </div>"""
    else:
        head_block = f"{header}\n{band_html}"

    return f"""\
  <section class="category-section{feature_cls} reveal" data-category="{cat_id}">
{head_block}
    <div class="product-grid">
{cards}
    </div>
{cta}
  </section>"""


def render_collections_band(doc, event_label=""):
    """Render the design-collections band that closes the product run.

    A collection is one artwork across a shared set of blanks, so listing every
    SKU as its own card would show the same tote once per design. Each card
    opens a panel holding that design's products instead. The cards are buttons,
    not links, so they carry no arrow; the Shop Now inside each panel is the
    real link and keeps its own.
    """
    collections = doc.get("collections") or []
    if not collections:
        return ""

    heading = doc.get("heading") or "HealthMerch Collections"
    intro = (doc.get("intro") or "").strip()
    intro_html = f"\n      <p>{intro}</p>" if intro else ""

    cards, panels = [], []
    for collection in collections:
        slug = collection["slug"]
        name = collection["name"]
        name_attr = name.replace('"', "&quot;")
        products = collection["products"]
        count = len(products)
        noun = "product" if count == 1 else "products"

        cover = _encode_url(collection.get("cover_image_url") or "") or _PRODUCT_PLACEHOLDER
        kicker = (collection.get("kicker") or "").strip()
        kicker_html = f'\n          <p class="coll-kicker">{kicker}</p>' if kicker else ""

        cards.append(f"""\
        <button type="button" class="coll-card" data-collection="{slug}" aria-expanded="false" aria-controls="coll-panel-{slug}">
          <div class="coll-cover"><img src="{cover}" alt="{name_attr} collection" loading="lazy" decoding="async" onerror="this.onerror=null;this.src='{_PRODUCT_PLACEHOLDER}'"></div>
          <div class="coll-body">
            <span class="coll-name">{name}</span>{kicker_html}
            <span class="coll-count">{count} {noun}</span>
          </div>
        </button>""")

        grid = "\n".join(render_product_card(p, event_label) for p in products)
        panels.append(f"""\
      <div class="coll-panel" id="coll-panel-{slug}" data-collection="{slug}" hidden>
        <div class="coll-panel-top">
          <div>
            <div class="coll-panel-title">{name}</div>
            <div class="coll-panel-note">{count} {noun} carrying this design.</div>
          </div>
          <button type="button" class="coll-close">Close</button>
        </div>
        <div class="product-grid">
{grid}
        </div>
      </div>""")

    cards_html = "\n".join(cards)
    panels_html = "\n".join(panels)

    return f"""\
<div class="collections reveal" id="collections">
  <div class="collections-inner">
    <div class="cat-header">
      <h2>{heading}</h2>{intro_html}
    </div>
    <div class="coll-grid">
{cards_html}
    </div>
{panels_html}
  </div>
</div>"""


# Who the campaign is pitched at. A campaign aimed at one service line rather
# than a whole hospital sets "audience_list" in its config to say so.
DEFAULT_AUDIENCE = [
    "Hospital Systems", "Health Networks", "Nursing Schools",
    "Clinics & Practices", "Home Health Agencies", "Long-Term Care Facilities",
    "Community Health Centers", "Employee Wellness Programs",
    "HR & Recognition Teams", "Healthcare Associations",
]


def render_audience_section(config):
    eyebrow = config.get("eyebrow", "")
    cta_url = config.get("cta_url", "https://meetings.hubspot.com/healthmerch/healthmerch-team-meeting")
    audience = [a.strip() for a in (config.get("audience_list") or DEFAULT_AUDIENCE) if a.strip()]
    audience_html = "\n".join(f"      <li>{html.escape(a)}</li>" for a in audience)

    heading = f"Ready to Order for {eyebrow}?" if eyebrow else "Ready to Get Started?"
    body = (
        f"Let's create an impactful {eyebrow} campaign together. "
        "Schedule a call with our team to discuss your promotional needs, quantities, and custom branding options."
        if eyebrow else
        "Schedule a call with our team to discuss your promotional needs, quantities, and custom branding options."
    )

    return f"""\
<section class="audience reveal">
  <div class="audience-inner">
    <div>
      <h2>{heading}</h2>
      <p>{body}</p>
      <a href="{cta_url}" class="audience-cta" target="_blank" rel="noopener">Schedule a Call &#8594;</a>
    </div>
    <ul class="audience-list">
{audience_html}
    </ul>
  </div>
</section>"""


def render_footer(config, slug):
    eyebrow   = config.get("eyebrow", "")
    cta_url   = config.get("cta_url", "https://meetings.hubspot.com/healthmerch/healthmerch-team-meeting")
    cta_label = config.get("cta_label", "Schedule a Call")

    collections_item = f'        <li><a href="/{slug}" style="color:#fff!important;font-weight:700">{eyebrow}</a></li>' if eyebrow else ""

    return f"""\
<div class="hm-footer">
  <div class="footer__inner">
    <div class="brand">
      <img src="{HM_LOGO_WHITE_URL}" alt="HealthMerch" onerror="this.src='{HM_LOGO_URL}'">
      <p>Promotional products that amplify your mission, inspire your team, and strengthen the communities you serve.</p>
    </div>
    <div>
      <h5>Collections</h5>
      <ul>
        <li><a href="/">All Campaigns</a></li>
{collections_item}
      </ul>
    </div>
    <div>
      <h5>Categories</h5>
      <ul>
        <li><a href="https://www.healthmerch.com/categories/apparel" target="_blank" rel="noopener">Apparel</a></li>
        <li><a href="https://www.healthmerch.com/categories/bags" target="_blank" rel="noopener">Bags &amp; Totes</a></li>
        <li><a href="https://www.healthmerch.com/categories/drinkware" target="_blank" rel="noopener">Drinkware</a></li>
        <li><a href="https://www.healthmerch.com/categories/wellness" target="_blank" rel="noopener">Wellness</a></li>
        <li><a href="https://www.healthmerch.com/categories/technology" target="_blank" rel="noopener">Technology</a></li>
        <li><a href="https://www.healthmerch.com/categories/office-supplies" target="_blank" rel="noopener">Office Supplies</a></li>
        <li><a href="https://www.healthmerch.com/categories/outdoor" target="_blank" rel="noopener">Outdoor &amp; Events</a></li>
      </ul>
    </div>
    <div>
      <h5>Contact</h5>
      <ul>
        <li><a href="mailto:hello@healthmerch.com">hello@healthmerch.com</a></li>
        <li><a href="{cta_url}" target="_blank" rel="noopener">{cta_label}</a></li>
        <li><a href="https://www.healthmerch.com/get-quote" target="_blank" rel="noopener">Request a Quote</a></li>
      </ul>
    </div>
  </div>
  <div class="footer__bottom">
    <span>&copy; 2026 HealthMerch &middot; All rights reserved.</span>
    <span>Promotional products for healthcare. Made with care.</span>
  </div>
</div>"""


def render_sticky_cta(config):
    cta_url   = config.get("cta_url", "https://meetings.hubspot.com/healthmerch/healthmerch-team-meeting")
    cta_label = config.get("cta_label", "Schedule a Call")
    return f"""\
<div class="sticky-cta" id="sticky-cta">
  <a href="{cta_url}" target="_blank" rel="noopener">{cta_label}</a>
  <button class="sticky-cta-dismiss" onclick="document.getElementById('sticky-cta').style.display='none'" aria-label="Dismiss">&times;</button>
</div>"""


_COLLECTIONS_JS = """// Design collections: one panel open at a time, opened from its own card.
(function () {
  const cards = document.querySelectorAll('.coll-card');
  if (!cards.length) return;
  const panels = document.querySelectorAll('.coll-panel');

  function closeAll() {
    cards.forEach(c => c.setAttribute('aria-expanded', 'false'));
    panels.forEach(p => { p.hidden = true; });
  }

  cards.forEach(card => {
    card.addEventListener('click', () => {
      const slug = card.dataset.collection;
      const panel = document.getElementById('coll-panel-' + slug);
      if (!panel) return;
      const wasOpen = !panel.hidden;
      closeAll();
      if (wasOpen) return;
      card.setAttribute('aria-expanded', 'true');
      panel.hidden = false;
      panel.scrollIntoView({ behavior: 'smooth', block: 'start' });
    });
  });

  document.querySelectorAll('.coll-close').forEach(btn => {
    btn.addEventListener('click', () => {
      const panel = btn.closest('.coll-panel');
      closeAll();
      if (!panel) return;
      const card = document.querySelector('.coll-card[data-collection="' + panel.dataset.collection + '"]');
      if (card) card.focus();
    });
  });

  document.addEventListener('keydown', e => {
    if (e.key === 'Escape') closeAll();
  });
})();

"""


def render_js(config=None, with_collections=True):
    # The footer colours are written by JS with !important, so a campaign theme
    # cannot reach them from CSS. Let the config set them instead.
    cfg = config or {}
    footer_bg = (cfg.get("footer_bg") or "#081a2e").strip()
    footer_fg = (cfg.get("footer_fg") or "rgba(255,255,255,0.78)").strip()

    # Plain string — not an f-string. The ${filter} below is JS template literal syntax.
    return ("""\
<script>
(function(){var s=document.createElement('style');s.textContent='.site-nav,.hm-footer{display:block!important}';document.head.appendChild(s);})();

const filterBtns = document.querySelectorAll('.filter-btn');
const sections = document.querySelectorAll('.category-section');
const collectionsBand = document.getElementById('collections');
const productsWrap = document.querySelector('.products-wrap');
filterBtns.forEach(btn => {
  btn.addEventListener('click', () => {
    filterBtns.forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    const filter = btn.dataset.category;
    // The collections band lives outside .products-wrap, so it is shown and
    // hidden by hand: visible on All Products and on its own button, out of the
    // way while a single product category is being looked at.
    const collectionsOnly = filter === 'collections';
    sections.forEach(section => {
      const show = !collectionsOnly && (filter === 'all' || section.dataset.category === filter);
      section.style.display = show ? 'block' : 'none';
      if (show) section.classList.add('visible');
    });
    if (collectionsBand) {
      collectionsBand.style.display = (filter === 'all' || collectionsOnly) ? 'block' : 'none';
      if (collectionsOnly) collectionsBand.classList.add('visible');
    }
    // Hiding the empty wrapper too, or its padding leaves a gap above the band.
    if (productsWrap) productsWrap.style.display = collectionsOnly ? 'none' : 'block';
    if (filter !== 'all') {
      setTimeout(() => {
        const target = collectionsOnly
          ? collectionsBand
          : document.querySelector(`.category-section[data-category="${filter}"]`);
        if (target) target.scrollIntoView({ behavior: 'smooth', block: 'start' });
      }, 50);
    }
  });
});

__COLLECTIONS_JS__if (window.IntersectionObserver) {
  const obs = new IntersectionObserver(entries => {
    entries.forEach(e => { if (e.isIntersecting) { e.target.classList.add('visible'); obs.unobserve(e.target); } });
  }, { threshold: 0.07 });
  document.querySelectorAll('.reveal').forEach(el => obs.observe(el));
} else {
  document.querySelectorAll('.reveal').forEach(el => el.classList.add('visible'));
}

(function () {
  // .cat-header is our own section heading, not platform chrome. Without it
  // the [class*="header"] sweep below hides every category title on the page.
  var protectedSelectors = 'nav.site-nav, .hm-footer, .cat-header';
  function hideThemeChrome() {
    document.querySelectorAll('header, footer, [class*="header"], [id*="header"], [class*="footer"], [id*="footer"]').forEach(function (el) {
      if (el.matches(protectedSelectors) || el.closest(protectedSelectors)) return;
      el.style.setProperty('display', 'none', 'important');
      el.style.setProperty('visibility', 'hidden', 'important');
      el.style.setProperty('height', '0', 'important');
      el.style.setProperty('overflow', 'hidden', 'important');
    });
    document.querySelectorAll('img[alt*="HealthMerch"], img[src*="healthmerch-logo"]').forEach(function (img) {
      if (img.closest(protectedSelectors)) return;
      var wrapper = img.closest('section, header, footer, .dnd-section, .row-fluid, .hs_cos_wrapper, .widget-type-logo, div');
      if (!wrapper || wrapper.matches(protectedSelectors) || wrapper.closest(protectedSelectors)) return;
      wrapper.style.setProperty('display', 'none', 'important');
      wrapper.style.setProperty('visibility', 'hidden', 'important');
      wrapper.style.setProperty('height', '0', 'important');
      wrapper.style.setProperty('overflow', 'hidden', 'important');
    });
  }
  function styleFooter() {
    var footer = document.querySelector('.hm-footer');
    if (footer) {
      footer.style.setProperty('background', '__FOOTER_BG__', 'important');
      footer.style.setProperty('color', '__FOOTER_FG__', 'important');
      footer.style.setProperty('display', 'block', 'important');
    }
  }
  hideThemeChrome();
  styleFooter();
  window.addEventListener('load', function() { hideThemeChrome(); styleFooter(); });
  setTimeout(function() { hideThemeChrome(); styleFooter(); }, 500);
  setTimeout(function() { hideThemeChrome(); styleFooter(); }, 1500);
})();
</script>""".replace("__COLLECTIONS_JS__", _COLLECTIONS_JS if with_collections else "")
            .replace("__FOOTER_BG__", footer_bg).replace("__FOOTER_FG__", footer_fg))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Build a HealthMerch lookbook HTML from campaign data.")
    parser.add_argument("--slug", default="nurses-week-26", help="Campaign slug (e.g. nurses-week-26)")
    args = parser.parse_args()
    slug = args.slug

    data_file   = f"data/{slug}.json"
    config_file = f"data/{slug}-config.json"
    output_file = f"output/{slug}.html"

    print(f"Building lookbook from {data_file}...")

    if not os.path.isfile(data_file):
        print(f"\nERROR: {data_file} not found.")
        print("Run validate.py first.")
        sys.exit(1)

    with open(data_file, "r", encoding="utf-8") as f:
        products = json.load(f)

    print(f"Loaded {len(products)} products.")

    if len(products) == 0:
        print("\nERROR: dataset has 0 products — nothing to build.")
        sys.exit(1)
    if len(products) < 4:
        print(f"  Warning: only {len(products)} products — recommended minimum is 4.")

    config = load_config(config_file)
    apply_custom_sections(config)

    # Campaign artwork replaces the catalogue photograph for a SKU. Product
    # names, prices and links still come only from the API; this swaps the
    # picture for one showing the campaign's own print.
    overrides = config.get("image_overrides") or {}
    if overrides:
        by_sku = {k.upper(): v for k, v in overrides.items()}
        swapped = 0
        for product in products:
            new_src = by_sku.get((product.get("sku") or "").upper())
            if new_src:
                product["image_url"] = new_src
                swapped += 1
        missing = set(by_sku) - {(p.get("sku") or "").upper() for p in products}
        print(f"  Image overrides: {swapped} product photo(s) replaced with campaign artwork.")
        if missing:
            print(f"  Warning: image_overrides name SKUs not on the page: {', '.join(sorted(missing))}")

    # A campaign can pull chosen SKUs to the front of their section; anything
    # not listed keeps its dataset order behind them.
    lead = [s.strip().upper() for s in (config.get("product_order") or []) if s.strip()]
    if lead:
        rank = {sku: i for i, sku in enumerate(lead)}
        products = sorted(products, key=lambda p: rank.get((p.get("sku") or "").upper(), len(rank)))
        print(f"  Product order: {len(lead)} SKU(s) pulled forward.")

    by_category = defaultdict(list)
    for product in products:
        api_cat = product.get("category", "")
        cat = api_cat if api_cat in CATEGORY_DISPLAY else "Other"
        by_category[cat].append(product)

    configured = [c.strip() for c in (config.get("category_order") or []) if c.strip()]
    if configured:
        unknown = [c for c in configured if c not in CATEGORY_DISPLAY]
        if unknown:
            print(f"  Warning: category_order names unknown sections: {', '.join(unknown)}")
        # Campaign sections always lead; category_order ranks the rest.
        custom = [c for c in CATEGORY_ORDER if c not in _STANDARD_CATEGORIES]
        base = custom + [c for c in configured if c in CATEGORY_DISPLAY and c not in custom]
        base += [c for c in CATEGORY_ORDER if c not in base]
        if "Other" not in base:
            base.append("Other")
        extended_order = base
    else:
        extended_order = CATEGORY_ORDER + (["Other"] if by_category["Other"] else [])
    populated = [cat for cat in extended_order if by_category[cat]]
    hidden    = [cat for cat in extended_order if not by_category[cat]]

    populated_display = [CATEGORY_DISPLAY.get(cat, cat) for cat in populated]

    cat_summary = ", ".join(
        f"{CATEGORY_DISPLAY[cat]} ({len(by_category[cat])})" for cat in populated
    )
    print(f"Categories rendered: {cat_summary}")
    if hidden:
        hidden_display = ", ".join(CATEGORY_DISPLAY.get(cat, cat) for cat in hidden)
        print(f"Categories hidden (0 products): {hidden_display}")

    # The eyebrow doubles as the chip on every card over $5. A long campaign name
    # reads badly in a small pill, so a campaign can set a shorter "tag_label".
    event_label = (config.get("tag_label") or "").strip() or config.get("eyebrow", "")
    collections_doc = load_collections(slug)
    has_collections = bool(collections_doc.get("collections"))
    css         = render_css(has_collections) + load_theme_css(slug)
    head        = render_head(config, slug)
    nav         = render_nav(config)
    hero        = render_hero(config)

    motw_sku = config.get("motw_sku", "").strip()
    motw_html = ""
    if motw_sku:
        motw_product = next((p for p in products if p.get("sku") == motw_sku), None)
        if motw_product:
            motw_html = render_motw(motw_product)

    filter_nav  = render_filter_nav(populated_display, has_collections)

    # Campaign image bands sit after the section named by their "after" value.
    bands = config.get("image_bands") or []
    inside_section = defaultdict(list)   # under the heading, above the products
    after_section = defaultdict(list)    # following the whole section
    for band in bands:
        target = (band.get("in") or "").strip()
        if target:
            inside_section[target].append(band)
        else:
            after_section[(band.get("after") or "").strip()].append(band)

    # The featured product slab can sit further down the page than the top.
    motw_before = (config.get("motw_before") or "").strip()

    rendered = []
    for cat in populated:
        label = CATEGORY_DISPLAY.get(cat, cat)

        if motw_before and label == motw_before and motw_html:
            rendered.append(motw_html)
            motw_html = ""

        inner = "\n".join(h for h in (render_image_band(b) for b in inside_section.get(label, [])) if h)
        rendered.append(render_category_section(
            label, by_category[cat], event_label, inner,
            feature=cat not in _STANDARD_CATEGORIES, band=label in CATEGORY_BANDS))
        for band in after_section.get(label, []):
            html = render_image_band(band)
            if html:
                rendered.append(html)

    if motw_before and motw_html:
        print(f"  Warning: motw_before names a section that is not rendered: {motw_before}")

    placed = {(b.get("in") or b.get("after") or "").strip() for b in bands}
    unknown = placed - set(populated_display)
    if unknown:
        print(f"  Warning: image_bands reference unknown sections: {', '.join(sorted(unknown))}")
    if bands:
        filled = sum(1 for b in bands if (b.get("src") or "").strip())
        print(f"  Image bands: {filled} of {len(bands)} slots have artwork.")

    sections = "\n\n".join(rendered)
    collections = render_collections_band(collections_doc, event_label)
    audience  = render_audience_section(config)
    footer    = render_footer(config, slug)
    sticky    = render_sticky_cta(config)
    js        = render_js(config, has_collections)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
{head}
<style>
{css}
</style>
</head>
<body>

{nav}

{hero}

{filter_nav}

{motw_html}

<div class="products-wrap">

{sections}

</div><!-- /products-wrap -->

{collections}

{audience}

{footer}

{sticky}

{js}

</body>
</html>"""

    os.makedirs("output", exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"Output written to {output_file}")
    print("Done.")


if __name__ == "__main__":
    main()
