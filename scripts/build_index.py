#!/usr/bin/env python3
"""
build_index.py — Rebuild output/index.html from data/index-slugs.json.

Reads:
  data/index-slugs.json          — ordered list of published slugs
  data/upcoming-campaigns.json   — planned campaigns not yet published
  data/{slug}-config.json        — per-page config (title, hero image, etc.)

Writes:
  output/index.html
  data/index-slugs.json          — updated in-place when --slug is used

Usage:
  # Rebuild index from current slug order:
  python scripts/build_index.py

  # Prepend a new slug (move to front if already present) then rebuild:
  python scripts/build_index.py --slug spring-summer-lookbook
"""

import argparse
import html as html_mod
import json
import logging
import os
import re
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("build_index")

ROOT         = Path(__file__).parent.parent
SLUGS_FILE   = ROOT / "data" / "index-slugs.json"
UPCOMING_FILE= ROOT / "data" / "upcoming-campaigns.json"
COLLECTIONS  = ROOT / "data" / "collections-slugs.json"
COLL_PAGES   = ROOT / "output" / "collections"
COLL_SHOWN   = 2
CURRENT_SHOWN= 6
OUTPUT_FILE  = ROOT / "output" / "index.html"
NETLIFY_BASE = "https://healthmerchcatalog.com"


def _load_json(path: Path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def _collection_cards() -> str:
    """The newest collections, read off their own built pages.

    A collection is appended to collections-slugs.json when it is approved, so
    the last entries are the newest. The picture and the campaign colour live
    in the page itself, the same two the hub reads, so a card here can never
    drift from the page it points at.
    """
    entries = _load_json(COLLECTIONS, [])[-COLL_SHOWN:][::-1]
    e = html_mod.escape
    cards = ""
    for entry in entries:
        page = COLL_PAGES / f"{entry['slug']}.html"
        if not page.exists():
            logger.warning("collections strip: %s is not built, leaving it out", entry["slug"])
            continue
        src = page.read_text(encoding="utf-8")
        hero = re.search(r'src="(/lifestyle/[^"]*/hero-1\.[a-z]+)"', src)
        # the campaign's own colour scale, past the shared HealthMerch ones
        shared = r"(?!navy|sky|slate|grey|gray|black|white|ink|line|green|coral)"
        accent = re.search(rf"--{shared}[a-z]+-600:\s*(#[0-9a-fA-F]{{6}})", src)
        if not hero:
            logger.warning("collections strip: %s has no hero image, leaving it out", entry["slug"])
            continue
        cards += f"""
      <a class="cstrip-card" href="/collections/{e(entry['slug'])}"
         style="--c:{accent.group(1) if accent else '#1f4477'}">
        <div class="cstrip-card__img" style="background-image:url('{e(hero.group(1))}')"
             role="img" aria-label="{e(entry['campaign'])} collection"></div>
        <div class="cstrip-card__body">
          <span class="cstrip-card__date">{e(entry['date'])}</span>
          <h3 class="cstrip-card__title">{e(entry['campaign'])}</h3>
          <p class="cstrip-card__desc">{e(entry['pitch'])}</p>
          <span class="cstrip-card__cta">View the collection <span aria-hidden="true">&rarr;</span></span>
        </div>
      </a>"""
    return cards


def build_index(slugs: list[str], upcoming: list[dict]) -> str:
    _gradients = [
        "linear-gradient(140deg, #143256 0%, #0d2440 60%, #081a2e 100%)",
        "linear-gradient(140deg, #1f4477 0%, #143256 60%, #0d2440 100%)",
        "linear-gradient(140deg, #2c5a99 0%, #143256 60%, #081a2e 100%)",
        "linear-gradient(140deg, #143256 0%, #0d2440 45%, #061220 100%)",
        "linear-gradient(140deg, #1f4477 0%, #0d2440 50%, #081a2e 100%)",
    ]
    arrow_svg = (
        '<svg width="16" height="16" viewBox="0 0 16 16" fill="none" '
        'stroke="currentColor" stroke-width="2" stroke-linecap="round" '
        'stroke-linejoin="round" aria-hidden="true"><path d="M3 8h10M9 4l4 4-4 4"/></svg>'
    )

    built_set = set(slugs)
    remaining_upcoming = [c for c in upcoming if c["slug"] not in built_set]
    next_campaign_title = remaining_upcoming[0]["title"] if remaining_upcoming else "New Campaign"

    cards_html = ""
    other_cards = []
    footer_links_html = ""
    first_title    = "Current campaign"
    first_eyebrow  = ""
    first_desc     = "Curated promotional products for your healthcare campaign."
    first_hero_img = ""

    for i, slug in enumerate(slugs):
        config_path = ROOT / "data" / f"{slug}-config.json"
        cfg = _load_json(config_path, {})

        eyebrow   = cfg.get("eyebrow", "")
        title     = cfg.get("page_title", slug)
        desc_list = cfg.get("description", [])
        desc      = desc_list[0] if desc_list else ""
        hero_img  = cfg.get("hero_image_url", "")
        # Cards are 16:9. A portrait photo needs a focal point or the crop
        # lands on the middle of the frame and cuts off faces.
        hero_pos  = cfg.get("hero_image_position", "")
        # a catalog and a campaign lookbook are different things, and the link
        # should say which one it opens
        cta_noun  = "catalog" if cfg.get("kind") == "catalog" else "lookbook"
        url       = f"{NETLIFY_BASE}/{slug}"

        if i == 0:
            first_title    = title
            first_eyebrow  = eyebrow
            first_hero_img = hero_img
            # the page's own line, not a generated stand-in
            first_desc     = desc or (
                f"Curated products for {eyebrow}." if eyebrow else first_desc
            )

        visual_style = (
            f"background-image: url('{hero_img}'); background-color: #0d2440;"
            + (f" background-position: {hero_pos};" if hero_pos else "")
            if hero_img else
            f"background: {_gradients[i % len(_gradients)]};"
        )

        card = f"""
    <article class="lb-card">
      <div class="lb-card__visual" style="{visual_style}">
        <span class="lb-card__eyebrow">{eyebrow}</span>
      </div>
      <div class="lb-card__body">
        <h2 class="lb-card__title">{title}</h2>
        <p class="lb-card__desc">{desc}</p>
        <a class="lb-card__cta" href="{url}">
          View {cta_noun} {arrow_svg}
        </a>
      </div>
    </article>"""

        # A new page goes to the front of the slug list, so the first few are
        # what teams are ordering now and the rest are the year behind them.
        if i < CURRENT_SHOWN:
            cards_html += card
        else:
            other_cards.append((cfg.get("campaign_date", ""), len(other_cards), card))

        footer_links_html += f'        <li><a href="{url}">{eyebrow or title}</a></li>\n'

    total = len(slugs)

    # The archive reads most recent campaign first. A page that runs all year
    # carries no date and keeps its place at the end rather than being given
    # one it does not have.
    dated   = sorted((c for c in other_cards if c[0]), key=lambda c: c[0], reverse=True)
    undated = [c for c in other_cards if not c[0]]
    other_cards_html = "".join(c[2] for c in dated + undated)

    collection_cards = _collection_cards()
    collections_section = f"""
<!-- ============== HEALTHMERCH COLLECTIONS ============== -->
<section class="cstrip reveal" id="collections">
  <div class="cstrip__inner">
    <div class="cstrip__head">
      <div>
        <span class="t-eyebrow">Awareness designs</span>
        <h2>HealthMerch Collections</h2>
        <p>Artwork drawn for the moment someone stops at your table. Put your logo on any of it.</p>
      </div>
      <a class="btn btn--secondary" href="/collections">View all collections {arrow_svg}</a>
    </div>
    <div class="cstrip-grid">{collection_cards}
    </div>
  </div>
</section>""" if collection_cards else ""

    other_section = f"""
<!-- ============== OTHER CAMPAIGNS ============== -->
<section class="lookbooks lookbooks--other reveal" id="other-campaigns">
  <div class="lookbooks__head">
    <span class="t-eyebrow">2026 archive</span>
    <h2>Other campaigns</h2>
    <p class="lookbooks__intro">Earlier campaigns from this year. Every product on them is still available to order.</p>
  </div>
  <div class="lookbooks-grid">{other_cards_html}
  </div>
</section>""" if other_cards_html else ""

    upcoming_cards = ""
    for j, campaign in enumerate(remaining_upcoming):
        if j == 0:
            ub_eyebrow = "Next up"
            ub_badge   = "In production"
            ub_class   = "upcoming-card"
        else:
            ub_eyebrow = "Coming soon"
            ub_badge   = "Planned"
            ub_class   = "upcoming-card upcoming-card--notify"
        upcoming_cards += f"""
      <div class="{ub_class}">
        <span class="upcoming-card__eyebrow">{ub_eyebrow}</span>
        <div class="upcoming-card__title">{campaign["title"]}</div>
        <div class="upcoming-card__date">{campaign["date"]}</div>
        <span class="upcoming-card__badge">{ub_badge}</span>
      </div>"""

    # four across is right for a full slate. One or two campaigns in that grid
    # leave a card stretched over a quarter of the page, so the grid narrows.
    n_up = len(remaining_upcoming)
    upcoming_grid_style = (
        f"grid-template-columns:repeat({n_up},1fr);max-width:{n_up * 300 + (n_up - 1) * 16}px;"
        if 0 < n_up < 3 else ""
    )
    upcoming_section = f"""
<!-- ============== UPCOMING CAMPAIGNS ============== -->
<section class="upcoming reveal">
  <div class="upcoming__inner">
    <div class="upcoming__head">
      <h2>Coming up next</h2>
      <p>Lookbooks in production. Check back, or schedule a call to get early access.</p>
    </div>
    <div class="upcoming-grid" style="{upcoming_grid_style}">{upcoming_cards}
    </div>
  </div>
</section>""" if upcoming_cards else ""

    hero_card_style = ""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width,initial-scale=1" />
<title>HealthMerch Lookbooks</title>
<meta name="description" content="Campaign lookbooks from HealthMerch — promotional products for healthcare organizations." />
<link rel="icon" type="image/png" href="/favicon.png">
<link rel="apple-touch-icon" href="/favicon.png">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Nunito+Sans:ital,opsz,wght@0,6..12,300;0,6..12,400;0,6..12,500;0,6..12,600;0,6..12,700;0,6..12,800;0,6..12,900;1,6..12,400;1,6..12,600&display=swap" rel="stylesheet">
<style>
:root {{
  --hm-navy-900:#081a2e;--hm-navy-800:#0d2440;--hm-navy-700:#143256;
  --hm-navy-600:#1f4477;--hm-navy-500:#2c5a99;--hm-navy-200:#b8c8df;
  --hm-navy-100:#dde6f1;--hm-navy-50:#eef3f9;
  --hm-sky-700:#3aa3da;--hm-sky-600:#61c5f7;--hm-sky-500:#82d2f9;
  --hm-sky-400:#a6dffb;--hm-sky-300:#c5eafc;--hm-sky-100:#ecf7fe;
  --hm-coral-500:#ea8474;--hm-green-600:#4f9e6c;
  --hm-ink:#0d1626;--hm-graphite:#353e5c;--hm-slate:#5a6478;--hm-mist:#8a92a3;
  --hm-line:#e3e6ec;--hm-line-soft:#eef0f4;--hm-bg-soft:#f5f5f5;
  --color-primary:var(--hm-navy-700);--color-primary-hover:var(--hm-navy-800);
  --color-primary-active:var(--hm-navy-900);
  --color-accent:var(--hm-sky-600);--color-accent-hover:var(--hm-sky-700);
  --color-accent-soft:var(--hm-sky-100);
  --font-sans:"Avenir Next","Avenir","Nunito Sans",-apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif;
  --fs-12:0.75rem;--fs-14:0.875rem;--fs-16:1rem;--fs-18:1.125rem;--fs-20:1.25rem;
  --fs-24:1.5rem;--fs-30:1.875rem;
  --fw-regular:400;--fw-medium:500;--fw-semibold:600;--fw-bold:700;
  --tracking-snug:-0.01em;--tracking-wider:0.12em;
  --radius-xs:4px;--radius-sm:6px;--radius-md:10px;--radius-lg:16px;
  --radius-xl:24px;--radius-2xl:32px;--radius-pill:999px;
  --shadow-sm:0 2px 6px rgba(20,50,86,0.08),0 1px 2px rgba(20,50,86,0.04);
  --shadow-md:0 8px 20px rgba(20,50,86,0.10),0 2px 4px rgba(20,50,86,0.05);
  --shadow-lg:0 18px 40px rgba(20,50,86,0.14),0 4px 8px rgba(20,50,86,0.06);
  --shadow-focus:0 0 0 3px rgba(97,197,247,0.40);
  --container:1240px;--container-wide:1400px;--gutter:24px;
  --ease-out:cubic-bezier(0.22,0.61,0.36,1);--dur-fast:140ms;--dur-base:220ms;
}}
*,*::before,*::after{{box-sizing:border-box;}}
html,body{{margin:0;padding:0;}}
html{{scroll-behavior:smooth;}}
body{{font-family:var(--font-sans);font-size:var(--fs-16);line-height:1.45;color:var(--hm-ink);background:#fff;-webkit-font-smoothing:antialiased;-moz-osx-font-smoothing:grayscale;text-rendering:optimizeLegibility;}}
img,svg{{display:block;max-width:100%;}}
button,input,select,textarea{{font:inherit;color:inherit;}}
a{{color:var(--color-primary);text-decoration:none;}}
a:hover{{color:var(--color-accent-hover);}}
.t-eyebrow{{font-size:var(--fs-12);font-weight:var(--fw-bold);text-transform:uppercase;letter-spacing:var(--tracking-wider);color:var(--color-accent);}}
.btn{{display:inline-flex;align-items:center;justify-content:center;gap:8px;height:48px;padding:0 22px;border-radius:var(--radius-pill);border:1.5px solid transparent;background:transparent;color:inherit;font-weight:var(--fw-semibold);font-size:var(--fs-16);letter-spacing:var(--tracking-snug);cursor:pointer;transition:background var(--dur-fast) var(--ease-out),color var(--dur-fast) var(--ease-out),border-color var(--dur-fast) var(--ease-out),transform var(--dur-fast) var(--ease-out),box-shadow var(--dur-fast) var(--ease-out);white-space:nowrap;text-decoration:none;user-select:none;}}
.btn:focus-visible{{outline:none;box-shadow:var(--shadow-focus);}}
.btn:active{{transform:translateY(1px);}}
.btn--primary{{background:var(--color-primary);color:#fff;border-color:var(--color-primary);}}
.btn--primary:hover{{background:var(--color-primary-hover);border-color:var(--color-primary-hover);color:#fff;}}
.btn--accent{{background:var(--color-accent);color:var(--hm-navy-900);border-color:var(--color-accent);}}
.btn--accent:hover{{background:var(--color-accent-hover);border-color:var(--color-accent-hover);color:#fff;}}
.btn--secondary{{background:#fff;color:var(--color-primary);border-color:var(--hm-navy-200);}}
.btn--secondary:hover{{border-color:var(--color-primary);background:var(--hm-navy-50);}}
.btn--ghost{{background:transparent;color:var(--color-primary);}}
.btn--ghost:hover{{background:var(--hm-navy-50);}}
.btn--on-dark{{background:#fff;color:var(--color-primary);border-color:#fff;}}
.btn--on-dark:hover{{background:var(--hm-sky-100);}}
.btn--lg{{height:56px;padding:0 28px;font-size:var(--fs-18);}}
.btn--sm{{height:36px;padding:0 14px;font-size:var(--fs-14);}}
.nav{{position:sticky;top:0;z-index:60;background:rgba(255,255,255,0.86);backdrop-filter:saturate(160%) blur(12px);-webkit-backdrop-filter:saturate(160%) blur(12px);border-bottom:1px solid var(--hm-line-soft);}}
.nav__inner{{max-width:var(--container-wide);margin:0 auto;padding:0 var(--gutter);height:76px;display:flex;align-items:center;justify-content:space-between;gap:24px;}}
.nav__logo img{{height:32px;}}
.nav__links{{display:flex;gap:4px;}}
.nav__links a{{padding:10px 16px;border-radius:var(--radius-pill);font-size:var(--fs-14);font-weight:var(--fw-semibold);color:var(--hm-graphite);transition:background var(--dur-fast) var(--ease-out),color var(--dur-fast) var(--ease-out);}}
.nav__links a:hover{{background:var(--hm-navy-50);color:var(--color-primary);}}
.nav__cta{{display:flex;align-items:center;gap:12px;}}
@media(max-width:900px){{.nav__links{{display:none;}}.nav__cta .btn--ghost{{display:none;}}}}
.hero{{position:relative;overflow:hidden;padding:80px 0 96px;background:radial-gradient(900px 500px at 110% -10%,rgba(97,197,247,0.18),transparent 60%),radial-gradient(700px 400px at -10% 30%,rgba(20,50,86,0.06),transparent 60%),#fff;}}
.hero__inner{{max-width:var(--container);margin:0 auto;padding:0 var(--gutter);display:grid;grid-template-columns:1.15fr 1fr;gap:64px;align-items:center;}}
@media(max-width:980px){{.hero{{padding:56px 0 64px;}}.hero__inner{{grid-template-columns:1fr;gap:40px;}}}}
.hero__eyebrow{{display:inline-flex;align-items:center;gap:8px;padding:6px 12px;border-radius:var(--radius-pill);background:var(--hm-navy-50);color:var(--hm-navy-700);font-size:var(--fs-12);font-weight:var(--fw-bold);letter-spacing:var(--tracking-wider);text-transform:uppercase;}}
.hero__eyebrow::before{{content:"";width:8px;height:8px;border-radius:50%;background:var(--hm-sky-600);}}
.hero h1{{font-size:clamp(2.4rem,5.4vw,4.25rem);line-height:1.04;letter-spacing:-0.024em;margin:20px 0 20px;font-weight:var(--fw-bold);color:var(--hm-ink);max-width:14ch;}}
.hero h1 em{{font-style:normal;color:var(--color-primary);background:linear-gradient(180deg,transparent 60%,rgba(97,197,247,0.30) 60% 92%,transparent 92%);padding:0 4px;}}
.hero__lead{{font-size:var(--fs-20);line-height:1.55;color:var(--hm-graphite);max-width:56ch;margin:0 0 32px;}}
.hero__ctas{{display:flex;flex-wrap:wrap;gap:12px;}}
.hero__trust{{margin-top:36px;display:flex;gap:24px;align-items:center;flex-wrap:wrap;color:var(--hm-slate);font-size:var(--fs-14);}}
.hero__trust strong{{color:var(--color-primary);font-weight:var(--fw-semibold);}}
.hero__trust .dot{{width:4px;height:4px;background:var(--hm-mist);border-radius:50%;}}
.hero__visual{{position:relative;aspect-ratio:1/1;max-height:560px;}}
.hero__card{{position:absolute;border-radius:var(--radius-2xl);overflow:hidden;box-shadow:var(--shadow-lg);}}
.hero__card--main{{inset:4% 12% 12% 8%;gap:18px;background:linear-gradient(140deg,var(--hm-navy-700) 0%,var(--hm-navy-800) 60%,var(--hm-navy-900) 100%);color:#fff;padding:68px 40px 36px;display:flex;flex-direction:column;justify-content:space-between;}}
.hero__card--main::after{{content:"";position:absolute;right:-80px;top:-80px;width:320px;height:320px;border-radius:50%;background:radial-gradient(circle at 30% 30%,var(--hm-sky-500),transparent 65%);opacity:0.55;pointer-events:none;}}
.hero__card--main h3{{font-size:var(--fs-30);line-height:1.15;letter-spacing:-0.01em;margin:0;max-width:14ch;font-weight:var(--fw-semibold);position:relative;}}
.hero__card--main p{{margin:12px 0 0;font-size:var(--fs-14);color:rgba(255,255,255,0.78);line-height:1.6;max-width:32ch;position:relative;}}
/* the sky card sits over the bottom right corner, so the figures keep to the
   left half of this one. They used to run under it and lose the last of them. */
.hero__card--main .meta{{display:flex;gap:20px 22px;flex-wrap:wrap;max-width:58%;color:rgba(255,255,255,0.7);font-size:var(--fs-12);position:relative;}}
.hero__card--main .meta strong{{display:block;color:#fff;font-size:var(--fs-20);font-weight:var(--fw-semibold);margin-top:2px;}}
.hero__card--accent{{right:0;bottom:4%;width:46%;aspect-ratio:1.55;background:var(--hm-sky-600);padding:24px;display:flex;flex-direction:column;justify-content:space-between;color:var(--hm-navy-900);}}
.hero__card--accent .label{{font-size:var(--fs-12);font-weight:var(--fw-bold);letter-spacing:var(--tracking-wider);text-transform:uppercase;}}
.hero__card--accent h4{{margin:0;font-size:var(--fs-24);line-height:1.15;font-weight:var(--fw-semibold);}}
.hero__card--accent .row{{display:flex;align-items:center;justify-content:space-between;}}
.hero__card--accent .icon{{width:36px;height:36px;border-radius:50%;background:rgba(255,255,255,0.4);display:flex;align-items:center;justify-content:center;}}
.hero__card--floater{{left:0;top:0;width:46%;background:#fff;padding:16px 18px;display:flex;align-items:center;gap:12px;}}
.hero__card--floater .av{{width:40px;height:40px;border-radius:50%;background:linear-gradient(135deg,var(--hm-coral-500),var(--hm-green-600));flex:0 0 40px;}}
.hero__card--floater p{{margin:0;font-size:var(--fs-12);color:var(--hm-graphite);line-height:1.4;}}
.hero__card--floater p strong{{color:var(--hm-ink);display:block;font-size:var(--fs-14);}}
/* The three cards overlap each other on purpose at full width. Below the
   breakpoint there is not room for that, and they ended up covering each
   other's words, so the stack collapses to the one card that says something. */
@media(max-width:1180px){{
  .hero__visual{{aspect-ratio:auto;max-height:none;width:100%;}}
  .hero__card{{position:static;}}
  .hero__card--main{{padding:32px;gap:28px;}}
  .hero__card--main h3{{font-size:var(--fs-24);}}
  .hero__card--main p{{max-width:none;}}
  .hero__card--main .meta{{max-width:none;}}
  .hero__card--accent,.hero__card--floater{{display:none;}}
}}
@media(max-width:980px){{.hero__visual{{max-width:520px;margin:0 auto;}}}}
.trusted{{border-top:1px solid var(--hm-line-soft);border-bottom:1px solid var(--hm-line-soft);padding:32px 0;background:#fff;}}
.trusted__inner{{max-width:var(--container-wide);margin:0 auto;padding:0 var(--gutter);display:flex;align-items:center;gap:32px;flex-wrap:wrap;justify-content:space-between;}}
.trusted__label{{font-size:var(--fs-12);font-weight:var(--fw-bold);letter-spacing:var(--tracking-wider);text-transform:uppercase;color:var(--hm-slate);white-space:nowrap;}}
.trusted__logos{{display:flex;gap:36px;flex-wrap:wrap;align-items:center;flex:1;justify-content:center;}}
.trusted__logo{{color:var(--color-primary);font-size:var(--fs-16);font-weight:var(--fw-semibold);letter-spacing:0.02em;opacity:0.85;transition:opacity var(--dur-fast) var(--ease-out);}}
.trusted__logo:hover{{opacity:1;}}
.lookbooks{{padding:96px 0;}}
.lookbooks__head{{max-width:var(--container);margin:0 auto;padding:0 var(--gutter) 56px;}}
.lookbooks__head h2{{font-size:clamp(2rem,4vw,3rem);margin:8px 0 12px;letter-spacing:-0.02em;line-height:1.1;max-width:24ch;}}
.lookbooks__intro{{font-size:var(--fs-18);color:var(--hm-graphite);max-width:60ch;line-height:1.6;margin:0;}}
.lookbooks-grid{{max-width:var(--container);margin:0 auto;padding:0 var(--gutter);display:grid;grid-template-columns:repeat(3,1fr);gap:16px;}}
@media(max-width:980px){{.lookbooks-grid{{grid-template-columns:repeat(2,1fr);}}}}
@media(max-width:540px){{.lookbooks-grid{{grid-template-columns:1fr;}}}}
.lb-card{{background:#fff;border:1px solid var(--hm-line);border-radius:var(--radius-xl);overflow:hidden;display:flex;flex-direction:column;transition:transform var(--dur-base) var(--ease-out),border-color var(--dur-base) var(--ease-out),box-shadow var(--dur-base) var(--ease-out);}}
.lb-card:hover{{transform:translateY(-4px);border-color:var(--hm-navy-200);box-shadow:var(--shadow-md);}}
.lb-card__visual{{aspect-ratio:16/9;background:linear-gradient(140deg,var(--hm-navy-700) 0%,var(--hm-navy-800) 60%,var(--hm-navy-900) 100%);background-size:cover;background-position:center;position:relative;overflow:hidden;display:flex;align-items:flex-end;justify-content:space-between;padding:16px 20px;}}
.lb-card__visual::before{{content:"";position:absolute;inset:0;background:linear-gradient(to top,rgba(8,26,46,.75) 0%,rgba(8,26,46,.2) 60%,transparent 100%);pointer-events:none;z-index:0;}}
.lb-card__visual::after{{content:"";position:absolute;right:-60px;top:-60px;width:200px;height:200px;border-radius:50%;background:radial-gradient(circle at 30% 30%,var(--hm-sky-500),transparent 65%);opacity:0.18;pointer-events:none;}}
.lb-card__eyebrow{{font-size:var(--fs-12);font-weight:var(--fw-bold);text-transform:uppercase;letter-spacing:var(--tracking-wider);color:var(--hm-sky-400);position:relative;z-index:1;background:rgba(8,26,46,0.45);backdrop-filter:blur(6px);-webkit-backdrop-filter:blur(6px);padding:4px 10px;border-radius:var(--radius-pill);border:1px solid rgba(97,197,247,0.25);}}
.lb-card__body{{padding:24px;flex:1;display:flex;flex-direction:column;}}
.lb-card__title{{font-size:var(--fs-20);font-weight:var(--fw-semibold);line-height:1.25;letter-spacing:-0.01em;color:var(--hm-ink);margin:0 0 10px;}}
.lb-card__desc{{font-size:var(--fs-14);line-height:1.6;color:var(--hm-graphite);margin:0 0 20px;flex:1;}}
.lb-card__cta{{display:inline-flex;align-items:center;gap:6px;font-size:var(--fs-14);font-weight:var(--fw-semibold);color:var(--color-primary);transition:color var(--dur-fast) var(--ease-out),gap var(--dur-fast) var(--ease-out);}}
.lb-card__cta:hover{{color:var(--color-accent-hover);gap:10px;}}
.org-bar{{background:var(--hm-navy-700);padding:28px 0;}}
.org-bar__inner{{max-width:var(--container-wide);margin:0 auto;padding:0 var(--gutter);display:flex;align-items:center;justify-content:center;}}
.org-bar__label{{font-size:var(--fs-18);color:rgba(255,255,255,.9);font-weight:var(--fw-semibold);line-height:1.4;text-align:center;}}
.upcoming{{padding:56px 0;background:var(--hm-bg-soft);}}
.upcoming__inner{{max-width:var(--container-wide);margin:0 auto;padding:0 var(--gutter);}}
.upcoming__head{{display:flex;align-items:baseline;justify-content:space-between;gap:1rem;margin-bottom:28px;flex-wrap:wrap;}}
.upcoming__head h2{{font-size:var(--fs-24);font-weight:var(--fw-semibold);color:var(--color-text);margin:0;}}
.upcoming__head p{{font-size:var(--fs-14);color:var(--color-text-muted);}}
.upcoming-grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:16px;}}
@media(max-width:900px){{.upcoming-grid{{grid-template-columns:repeat(2,1fr);}}}}
@media(max-width:500px){{.upcoming-grid{{grid-template-columns:1fr;}}}}
.upcoming-card{{background:#fff;border:1px solid var(--hm-line);border-radius:16px;padding:24px 20px;display:flex;flex-direction:column;gap:12px;}}
.upcoming-card__eyebrow{{font-size:var(--fs-12);font-weight:var(--fw-bold);letter-spacing:var(--tracking-wider);text-transform:uppercase;color:var(--hm-mist);}}
.upcoming-card__title{{font-size:var(--fs-18);font-weight:var(--fw-semibold);color:var(--color-text);line-height:1.25;}}
.upcoming-card__date{{font-size:var(--fs-14);color:var(--color-text-muted);}}
.upcoming-card__badge{{display:inline-flex;align-items:center;gap:6px;margin-top:auto;font-size:var(--fs-12);font-weight:var(--fw-semibold);color:var(--hm-sky-700);background:var(--hm-sky-100);padding:4px 10px;border-radius:100px;width:fit-content;}}
.upcoming-card__badge::before{{content:'';width:6px;height:6px;border-radius:50%;background:var(--hm-sky-600);}}
.upcoming-card--notify{{border-style:dashed;background:transparent;}}
.upcoming-card--notify .upcoming-card__badge{{color:var(--hm-mist);background:var(--hm-line-soft);}}
.upcoming-card--notify .upcoming-card__badge::before{{background:var(--hm-mist);}}
.cstrip{{padding:72px 0;background:var(--hm-navy-50);}}
.cstrip__inner{{max-width:var(--container);margin:0 auto;padding:0 var(--gutter);}}
.cstrip__head{{display:flex;align-items:flex-end;justify-content:space-between;gap:24px;flex-wrap:wrap;margin-bottom:28px;}}
.cstrip__head h2{{font-size:clamp(1.75rem,3.2vw,2.5rem);margin:8px 0 10px;letter-spacing:-0.02em;line-height:1.1;}}
.cstrip__head p{{font-size:var(--fs-16);color:var(--hm-graphite);max-width:52ch;margin:0;line-height:1.6;}}
.cstrip-grid{{display:grid;grid-template-columns:repeat(2,1fr);gap:16px;}}
@media(max-width:880px){{.cstrip-grid{{grid-template-columns:1fr;}}}}
.cstrip-card{{display:grid;grid-template-columns:40% 1fr;background:#fff;border:1px solid var(--hm-line);border-radius:var(--radius-xl);overflow:hidden;color:inherit;transition:transform var(--dur-base) var(--ease-out),border-color var(--dur-base) var(--ease-out),box-shadow var(--dur-base) var(--ease-out);}}
.cstrip-card:hover{{transform:translateY(-4px);border-color:var(--hm-navy-200);box-shadow:var(--shadow-md);}}
@media(max-width:520px){{.cstrip-card{{grid-template-columns:1fr;}}}}
.cstrip-card__img{{background-size:cover;background-position:center;min-height:100%;border-right:3px solid var(--c);}}
@media(max-width:520px){{.cstrip-card__img{{aspect-ratio:16/9;border-right:0;border-bottom:3px solid var(--c);}}}}
.cstrip-card__body{{padding:22px 24px;display:flex;flex-direction:column;}}
.cstrip-card__date{{font-size:var(--fs-12);font-weight:var(--fw-bold);letter-spacing:var(--tracking-wider);text-transform:uppercase;color:var(--c);}}
.cstrip-card__title{{font-size:var(--fs-20);font-weight:var(--fw-semibold);line-height:1.25;letter-spacing:-0.01em;color:var(--hm-ink);margin:6px 0 8px;}}
.cstrip-card__desc{{font-size:var(--fs-14);line-height:1.6;color:var(--hm-graphite);margin:0 0 18px;flex:1;}}
.cstrip-card__cta{{display:inline-flex;align-items:center;gap:6px;font-size:var(--fs-14);font-weight:var(--fw-semibold);color:var(--color-primary);transition:gap var(--dur-fast) var(--ease-out);}}
.cstrip-card:hover .cstrip-card__cta{{gap:10px;color:var(--color-accent-hover);}}
.lookbooks--other{{padding-top:72px;}}
.audience{{padding:96px 0;background:var(--color-primary);color:#fff;position:relative;overflow:hidden;}}
.audience::before{{content:"";position:absolute;right:-200px;top:-200px;width:700px;height:700px;border-radius:50%;background:radial-gradient(circle at 30% 30%,var(--hm-sky-600),transparent 60%);opacity:0.18;pointer-events:none;}}
.audience__inner{{max-width:var(--container);margin:0 auto;padding:0 var(--gutter);display:grid;grid-template-columns:1fr 1.2fr;gap:64px;align-items:start;position:relative;}}
@media(max-width:980px){{.audience__inner{{grid-template-columns:1fr;gap:40px;}}}}
.audience .t-eyebrow{{color:var(--hm-sky-400);}}
.audience h2{{font-size:clamp(2rem,4vw,3rem);line-height:1.1;letter-spacing:-0.02em;margin:8px 0 16px;max-width:18ch;color:#fff;font-weight:var(--fw-bold);}}
.audience p{{color:rgba(255,255,255,0.78);font-size:var(--fs-18);line-height:1.6;max-width:50ch;margin:0 0 24px;}}
.audience-list{{display:grid;grid-template-columns:repeat(2,1fr);gap:8px 16px;padding:0;}}
@media(max-width:540px){{.audience-list{{grid-template-columns:1fr;}}}}
.audience-list li{{list-style:none;padding:14px 16px;background:rgba(255,255,255,0.06);border:1px solid rgba(255,255,255,0.10);border-radius:var(--radius-md);display:flex;align-items:center;gap:10px;font-size:var(--fs-14);color:rgba(255,255,255,0.92);}}
.audience-list li::before{{content:"";width:6px;height:6px;border-radius:50%;background:var(--hm-sky-500);flex:0 0 6px;}}
footer.site{{background:var(--hm-navy-900);color:rgba(255,255,255,0.78);padding:80px 0 32px;}}
.footer__inner{{max-width:var(--container-wide);margin:0 auto;padding:0 var(--gutter);display:grid;grid-template-columns:1.4fr repeat(3,1fr);gap:48px;}}
@media(max-width:760px){{.footer__inner{{grid-template-columns:1fr 1fr;}}}}
@media(max-width:460px){{.footer__inner{{grid-template-columns:1fr;}}}}
footer.site h5{{margin:0 0 16px;font-size:var(--fs-12);text-transform:uppercase;letter-spacing:var(--tracking-wider);color:rgba(255,255,255,0.5);font-weight:var(--fw-bold);}}
footer.site ul{{list-style:none;padding:0;margin:0;display:flex;flex-direction:column;gap:10px;}}
footer.site a{{color:rgba(255,255,255,0.78);font-size:var(--fs-14);}}
footer.site a:hover{{color:#fff;}}
footer.site .brand img{{height:32px;margin-bottom:16px;background:#fff;border-radius:6px;padding:4px 10px;}}
footer.site .brand p{{font-size:var(--fs-14);line-height:1.6;max-width:32ch;margin:0;}}
.footer__bottom{{max-width:var(--container-wide);margin:64px auto 0;padding:24px var(--gutter) 0;border-top:1px solid rgba(255,255,255,0.10);display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:16px;font-size:var(--fs-12);color:rgba(255,255,255,0.5);}}
.reveal{{opacity:0;transform:translateY(16px);transition:opacity 0.8s var(--ease-out),transform 0.8s var(--ease-out);}}
.reveal.in{{opacity:1;transform:none;}}
@media(prefers-reduced-motion:reduce){{.reveal{{opacity:1;transform:none;transition:none;}}}}
.mob-sticky-cta{{display:none;position:fixed;bottom:0;left:0;right:0;z-index:80;padding:10px 16px;padding-bottom:max(14px,env(safe-area-inset-bottom,14px));background:rgba(255,255,255,0.97);backdrop-filter:saturate(180%) blur(12px);border-top:1px solid var(--hm-line);box-shadow:0 -4px 20px rgba(8,26,46,0.10);align-items:center;gap:10px;transform:translateY(100%);transition:transform 300ms cubic-bezier(0.22,0.61,0.36,1);}}
.mob-sticky-cta.is-visible{{transform:translateY(0);}}
@media(max-width:760px){{.mob-sticky-cta{{display:flex;}}}}
.mob-sticky-cta__btn{{flex:1;display:flex;align-items:center;justify-content:center;gap:8px;height:50px;background:var(--hm-navy-700);color:#fff;border-radius:var(--radius-pill);font-weight:var(--fw-semibold);font-size:var(--fs-16);letter-spacing:-0.01em;text-decoration:none;transition:background 140ms;}}
.mob-sticky-cta__btn:hover{{background:var(--hm-navy-800);color:#fff;}}
.mob-sticky-cta__dismiss{{width:36px;height:36px;flex-shrink:0;display:flex;align-items:center;justify-content:center;border:none;background:var(--hm-navy-50);border-radius:50%;cursor:pointer;color:var(--hm-slate);}}
.mob-sticky-cta__dismiss:hover{{background:var(--hm-navy-100);}}
@media(max-width:760px){{body{{padding-bottom:max(80px,calc(70px + env(safe-area-inset-bottom,0px)));}}}}
</style>
</head>
<body>

<!-- NAV -->
<header class="nav">
  <div class="nav__inner">
    <a class="nav__logo" href="/"><img src="https://677757.fs1.hubspotusercontent-na1.net/hubfs/677757/healthmerch-logo.png" alt="HealthMerch" /></a>
    <nav class="nav__links" aria-label="Primary">
      <a href="#lookbooks">All lookbooks</a>
      <a href="https://www.healthmerch.com" target="_blank" rel="noopener">Shop all products</a>
    </nav>
    <div class="nav__cta">
      <a class="btn btn--ghost btn--sm" href="https://www.healthmerch.com" target="_blank" rel="noopener">healthmerch.com</a>
      <a class="btn btn--primary btn--sm" href="https://meetings.hubspot.com/healthmerch/healthmerch-team-meeting" target="_blank" rel="noopener">Schedule a Call</a>
    </div>
  </div>
</header>

<!-- HERO -->
<section class="hero">
  <div class="hero__inner">
    <div>
      <span class="hero__eyebrow">Campaign Lookbooks</span>
      <h1>Products built for <em>healthcare</em> campaigns.</h1>
      <p class="hero__lead">Browse curated lookbooks for your next health fair, awareness campaign, or team recognition event. Each one is built around your mission and ready to order.</p>
      <div class="hero__ctas">
        <a class="btn btn--primary btn--lg" href="https://meetings.hubspot.com/healthmerch/healthmerch-team-meeting" target="_blank" rel="noopener">Schedule a Call</a>
        <a class="btn btn--secondary btn--lg" href="https://www.healthmerch.com" target="_blank" rel="noopener">Explore all products</a>
      </div>
      <div class="hero__trust">
        <span><strong>{total} active lookbooks</strong> &middot; 2026</span>
        <span class="dot"></span>
        <span><strong>Free mockups</strong> for every campaign</span>
      </div>
    </div>
    <div class="hero__visual" aria-hidden="true">
      <div class="hero__card hero__card--main" style="{hero_card_style}">
        <div>
          <span style="position:relative;font-size:var(--fs-12);color:var(--hm-sky-400);font-weight:var(--fw-bold);letter-spacing:var(--tracking-wider);text-transform:uppercase;">Current campaign</span>
          <h3>{first_title}</h3>
          <p>{first_desc}</p>
        </div>
        <div class="meta">
          <div>Lookbooks<strong>{total}</strong></div>
          <div>Year<strong>2026</strong></div>
          <div>Delivery<strong>10–14 days</strong></div>
        </div>
      </div>
      <div class="hero__card hero__card--accent">
        <span class="label">Next campaign</span>
        <h4>{next_campaign_title}</h4>
      </div>
      <div class="hero__card hero__card--floater">
        <div class="av"></div>
        <p><strong>Free samples available</strong>For all qualified leads</p>
      </div>
    </div>
  </div>
</section>

<!-- ORG LOGO BAR -->
<div class="org-bar">
  <div class="org-bar__inner">
    <p class="org-bar__label">Trusted by 1,000+ Healthcare Organizations in the US</p>
  </div>
</div>

<!-- JUMP TO -->
<section class="trusted">
  <div class="trusted__inner">
    <span class="trusted__label">Campaigns</span>
    <div class="trusted__logos">
      <a class="trusted__logo" href="#lookbooks">Nurses Week</a>
      <a class="trusted__logo" href="#lookbooks">PRIDE</a>
      <a class="trusted__logo" href="#lookbooks">Health Fairs</a>
      <a class="trusted__logo" href="#lookbooks">Recognition</a>
      <a class="trusted__logo" href="https://meetings.hubspot.com/healthmerch/healthmerch-team-meeting" target="_blank" rel="noopener">Custom Campaign &#8594;</a>
    </div>
  </div>
</section>

<!-- LOOKBOOKS GRID -->
<section class="lookbooks reveal" id="lookbooks">
  <div class="lookbooks__head">
    <span class="t-eyebrow">Ordering now</span>
    <h2>Current campaigns</h2>
    <p class="lookbooks__intro">Click any lookbook to browse products, pricing, and ordering options tailored to your campaign.</p>
  </div>
  <div class="lookbooks-grid">{cards_html}
  </div>
</section>

{collections_section}

{other_section}

{upcoming_section}

<!-- AUDIENCE / CTA -->
<section class="audience reveal">
  <div class="audience__inner">
    <div>
      <span class="t-eyebrow">Who we serve</span>
      <h2>Built for the organizations doing the work in their community.</h2>
      <p>We work with healthcare organizations in the US, from hospitals to nonprofits, that need promotional products for events, health campaigns, and recognition programs.</p>
      <a class="btn btn--accent" href="https://meetings.hubspot.com/healthmerch/healthmerch-team-meeting" target="_blank" rel="noopener">Schedule a Call</a>
    </div>
    <ul class="audience-list">
      <li>FQHCs (Federally Qualified Health Centers)</li>
      <li>Community-Based Organizations (CBOs)</li>
      <li>Hospitals &amp; health-related orgs</li>
      <li>Health-related associations</li>
      <li>LGBTQ+ friendly organizations</li>
      <li>State and local health departments</li>
      <li>Health conference exhibitors</li>
      <li>Health conference organizers</li>
      <li>Health marketing agencies</li>
      <li>HR, Outreach &amp; Program teams</li>
    </ul>
  </div>
</section>

<!-- FOOTER -->
<footer class="site">
  <div class="footer__inner">
    <div class="brand">
      <img src="https://677757.fs1.hubspotusercontent-na1.net/hubfs/677757/healthmerch-logo.png" alt="HealthMerch" />
      <p>Promotional products that amplify your mission, inspire your team, and strengthen the communities you serve.</p>
    </div>
    <div>
      <h5>Collections</h5>
      <ul>
{footer_links_html}      </ul>
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
        <li><a href="https://meetings.hubspot.com/healthmerch/healthmerch-team-meeting" target="_blank" rel="noopener">Schedule a Call</a></li>
        <li><a href="https://www.healthmerch.com/get-quote" target="_blank" rel="noopener">Request a Quote</a></li>
      </ul>
    </div>
  </div>
  <div class="footer__bottom">
    <span>&copy; 2026 HealthMerch &middot; All rights reserved.</span>
    <span>Promotional products for healthcare. Made with care.</span>
  </div>
</footer>

<!-- Mobile sticky CTA -->
<div class="mob-sticky-cta" id="mobStickyCta">
  <a href="https://meetings.hubspot.com/healthmerch/healthmerch-team-meeting" target="_blank" rel="noopener" class="mob-sticky-cta__btn">
    <svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="3" width="12" height="12" rx="2"/><path d="M6 7h6M6 10h4"/></svg>
    Schedule a Call
  </a>
  <button class="mob-sticky-cta__dismiss" id="mobStickyDismiss" aria-label="Dismiss">
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="2" y1="2" x2="12" y2="12"/><line x1="12" y1="2" x2="2" y2="12"/></svg>
  </button>
</div>

<script>
(function () {{
  var cta = document.getElementById('mobStickyCta');
  var dismiss = document.getElementById('mobStickyDismiss');
  if (!cta) return;
  if (sessionStorage.getItem('lbCtaDismissed')) return;
  var shown = false;
  function onScroll() {{
    if (!shown && window.scrollY > 300) {{
      shown = true; cta.classList.add('is-visible');
      window.removeEventListener('scroll', onScroll);
    }}
  }}
  window.addEventListener('scroll', onScroll, {{ passive: true }});
  dismiss.addEventListener('click', function () {{
    cta.classList.remove('is-visible');
    sessionStorage.setItem('lbCtaDismissed', '1');
  }});
}})();

(function () {{
  if (!window.IntersectionObserver) {{
    document.querySelectorAll('.reveal').forEach(function (el) {{ el.classList.add('in'); }});
    return;
  }}
  var obs = new IntersectionObserver(function (entries) {{
    entries.forEach(function (e) {{
      if (e.isIntersecting) {{ e.target.classList.add('in'); obs.unobserve(e.target); }}
    }});
  }}, {{ threshold: 0.07 }});
  document.querySelectorAll('.reveal').forEach(function (el) {{ obs.observe(el); }});
}})();

(function () {{
  var protectedSelectors = 'header.nav, footer.site';
  function hideThemeChrome() {{
    document.querySelectorAll('header, footer, [class*="header"], [id*="header"], [class*="footer"], [id*="footer"]').forEach(function (el) {{
      if (el.matches(protectedSelectors) || el.closest(protectedSelectors)) return;
      el.style.setProperty('display', 'none', 'important');
      el.style.setProperty('visibility', 'hidden', 'important');
      el.style.setProperty('height', '0', 'important');
      el.style.setProperty('overflow', 'hidden', 'important');
    }});
    document.querySelectorAll('img[alt*="HealthMerch"], img[src*="healthmerch-logo"]').forEach(function (img) {{
      if (img.closest(protectedSelectors)) return;
      var wrapper = img.closest('section, header, footer, .dnd-section, .row-fluid, .hs_cos_wrapper, .widget-type-logo, div');
      if (!wrapper || wrapper.matches(protectedSelectors) || wrapper.closest(protectedSelectors)) return;
      wrapper.style.setProperty('display', 'none', 'important');
      wrapper.style.setProperty('visibility', 'hidden', 'important');
      wrapper.style.setProperty('height', '0', 'important');
      wrapper.style.setProperty('overflow', 'hidden', 'important');
    }});
  }}
  hideThemeChrome();
  window.addEventListener('load', hideThemeChrome);
  setTimeout(hideThemeChrome, 500);
  setTimeout(hideThemeChrome, 1500);
}})();
</script>
</body>
</html>"""


def main():
    parser = argparse.ArgumentParser(description="Rebuild output/index.html")
    parser.add_argument(
        "--slug",
        help="Prepend this slug to index-slugs.json (moves to front if already present)",
    )
    args = parser.parse_args()

    slugs    = _load_json(SLUGS_FILE, [])
    upcoming = _load_json(UPCOMING_FILE, [])

    if args.slug:
        # Move to front (remove if already present, then insert at 0)
        if args.slug in slugs:
            slugs.remove(args.slug)
        slugs.insert(0, args.slug)
        with open(SLUGS_FILE, "w", encoding="utf-8") as f:
            json.dump(slugs, f, indent=2)
        logger.info("index-slugs.json updated: %s", slugs)

    if not slugs:
        logger.error("No slugs found in %s — nothing to build", SLUGS_FILE)
        sys.exit(1)

    html = build_index(slugs, upcoming)
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(html, encoding="utf-8")
    logger.info("Built %s (%d chars, %d pages)", OUTPUT_FILE, len(html), len(slugs))


if __name__ == "__main__":
    main()
