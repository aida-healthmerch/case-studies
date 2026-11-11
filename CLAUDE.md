# HealthMerch Case Studies — Project Rules

## Golden Rule — Content Accuracy

NEVER invent client names, results, quotes, or statistics. Every claim must come from information the user provides. If a detail is missing, leave a placeholder and ask the user rather than guessing.

---

## Writing Style

**Punctuation**
- Never use em dashes or hyphens used as dashes in prose. Rewrite as two sentences or use a comma.
- Never use ellipses for stylistic effect.

**Banned words and phrases**
Never use: "It's worth noting," "That said," "In other words," "Dive into," "Delve into," "Unpack," "Unlock," "Leverage," "Game-changer," "Groundbreaking," "Revolutionize," "Empower," "Journey" (in health or personal growth context), "In conclusion," "Seamless," "Streamline," "Robust," "Ecosystem," "Cutting-edge," "Innovative," "Transformative," "Actionable," "Takeaway," "At the end of the day," "Move the needle," "Deep dive," "Moreover," "Furthermore," "Additionally," "Importantly," "Synergies," "Holistic approach," "Leverage our learnings," "Navigate the complexities of," "In an ever-changing landscape," "This signals that," "This underscores," "Foster a culture of," "Lean into our strengths."

**Sentence structure**
- No bullet lists in conversational prose. Write in direct sentences.
- No transition words opening paragraphs: "Moreover," "Furthermore," "That said," "Additionally."
- Every sentence must sound natural spoken aloud.

**Banned patterns**
- No forced negation constructions ("not this but that").
- No staccato repetitions.
- No excessive adverbs.
- No bold word + colon + bullet list.
- No corporate therapist voice.
- No generic bow conclusions.
- Every paragraph must have a plain, stateable point.

---

## Design Systems

- HealthMerch brand guidelines: https://healthmerchcatalog.com/brandguidelines/
- Say it with a Condom brand guidelines: https://healthmerchcatalog.com/siwac/brandguidelines/
- Follow top UX/UI principles: aligned text, no overlapping structures, all text readable.

---

## Platform Rules (Netlify + HubSpot)

The site is deployed on Netlify at healthmerchcatalog.com. HubSpot scripts run on the page and override CSS on native HTML elements. Key workarounds:

- Never use `<footer>` — use `<div class="hm-footer">` instead. Platform CSS targets `footer {}` and overrides background to white.
- Never use `<header>` for our nav — use `<nav class="site-nav">` or `<header class="nav">`.
- When platform CSS overrides a style even with `!important` in a stylesheet, apply the style via JavaScript `element.style.setProperty('property', 'value', 'important')`.
- Apply filters and layout-critical styles to wrapper `<div>` elements, not directly on `<img>` tags. The platform resets CSS on img elements.

---

## Arrow / Link Rule

Only add arrow icons (→ or SVG arrows) to elements that are actual clickable links (`<a>` tags). Never add arrows to static `<div>` or `<span>` elements.

---

## Page Type: Case Studies

Case study pages live at healthmerchcatalog.com under their own slug (e.g. `/community-health-network-2026`).

- Built manually: user provides client details, results, and quotes in chat. HTML is hand-crafted.
- One page per client story.
- Structure: hero with client name and headline outcome stat, challenge section, solution section, results section (stat cards), optional quote block, CTA.
- Design follows HealthMerch brand guidelines (navy/sky palette, Nunito Sans font).
- No Google Sheet involvement — content comes directly from user in chat.

---

## Pipeline Overview

```
User provides client content in chat
  → scripts/build.py builds individual case study HTML from data/{slug}-config.json
  → output/          all HTML + assets served by Netlify
  → data/index-slugs.json  source of truth for page order on the site index
```

**Key files**
- `scripts/build.py` — case study page builder
- `data/index-slugs.json` — ordered list of published slugs
- `data/{slug}-config.json` — case study config (client name, stats, sections, CTA, etc.)
- `output/index.html` — site index page
- `output/{slug}.html` — individual case study pages
- `output/favicon.png` — site favicon

---

## Config Schema (`data/{slug}-config.json`)

```json
{
  "page_title": "Compelling headline about the outcome",
  "client": "Client Organization Name",
  "cta_label": "Schedule a Call",
  "cta_url": "https://meetings.hubspot.com/healthmerch/healthmerch-team-meeting",
  "stats": [
    { "value": "12,000", "label": "Items ordered" },
    { "value": "3 weeks", "label": "Turnaround time" }
  ],
  "sections": [
    {
      "type": "text",
      "eyebrow": "The Challenge",
      "heading": "Section heading",
      "paragraphs": ["Paragraph one.", "Paragraph two."]
    },
    {
      "type": "quote",
      "quote": "The quote text here.",
      "attribution": "Name, Title, Organization"
    },
    {
      "type": "results",
      "eyebrow": "Results",
      "heading": "What we delivered",
      "results": [
        { "value": "98%", "label": "On-time delivery" },
        { "value": "$42", "label": "Average unit cost" }
      ]
    }
  ]
}
```

---

## Workflow

- Do not push to main until the user approves the final output. Show previews first.
- Before any UI change, check against the HealthMerch design system and standard UX/UI rules.
- When a new case study is added: update `data/index-slugs.json` and rebuild the index page.
