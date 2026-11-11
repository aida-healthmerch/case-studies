#!/usr/bin/env python3
"""
generate_copy.py — AI copy generation for HealthMerch lookbook campaigns.

Generates two copy fields per campaign:
  - intro_copy   : 1–2 sentences, action-oriented, buyer-addressed
  - description  : 2–3 sentences as a list[str], campaign purpose + impact

Does NOT generate:
  - page_title   (verbatim from sheet, never overridden)
  - CTA fields   (verbatim from sheet, never overridden)

Does NOT read or write any sheet values.
Does NOT touch products.

Public API
----------
generate_copy(event_name: str, slug: str) -> dict[str, str | list[str]]

    Returns:
        {
            "intro_copy":  str,
            "description": list[str]
        }

    Raises:
        CopyGenerationError: if the API call fails or returns malformed JSON.

Environment
-----------
Requires ANTHROPIC_API_KEY to be set in the environment.
"""

import json
import logging
import os

from anthropic import Anthropic

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 300

_SYSTEM_PROMPT = """\
You are a copywriter for HealthMerch — the only promotional products partner \
that combines healthcare expertise, tailored solutions, and hassle-free service \
to help healthcare organizations achieve their mission.

ABOUT HEALTHMERCH
HealthMerch delivers promotional products that amplify missions, inspire teams, \
and strengthen the communities healthcare organizations serve. We make it \
effortless for healthcare organizations to connect meaningfully with their \
communities through thoughtfully designed products.

TARGET BUYERS
Outreach Managers, Program Directors, HR Managers, Marketing Managers, and \
Event Planners at: FQHCs, CBOs, hospitals, nonprofits, LGBTQ+-friendly \
organizations, state/local health departments, and health conference exhibitors. \
Address them as the decision-maker placing the order — not as event attendees.

BRAND VOICE
- Tone: approachable, compassionate, and professional
- Voice: friendly, bold, knowledgeable; focus on valuable insights
- Language: simple, clear, easy to understand, and client-focused
- No fluff, no filler — every word earns its place

BRAND PROMISE
Help buyers effectively communicate their message, engage their community, \
and achieve healthier outcomes with high-quality, mission-aligned products.

MESSAGING PILLARS
Community Engagement · Purposeful Innovation · Practical Solutions · Client Success

LENGTH RULE — HARD CONSTRAINT
Every text block you write must fit in 4 lines or fewer on a web page. \
This means: intro_copy ≤ 20 words; each description sentence ≤ 20 words. \
Never exceed these limits under any circumstances."""

_USER_TEMPLATE = """\
Campaign: {event_name}
URL slug (reference only, do not echo): {slug}{notes_block}

Write exactly three fields — no others:

page_title — 3-7 words. A compelling headline that evokes purpose or emotion. \
NOT just "{event_name} Lookbook". Under 42 characters total. \
Lead with a benefit, action, or celebration relevant to the event.

intro_copy — 2-3 sentences, 50-65 words total. Lead with the event name. \
Action-oriented and warm. Address the healthcare buyer directly. \
Explain why this event matters for their organization and community. No product mentions.

description — exactly 2 sentences as a JSON array of strings. Each sentence \
max 20 words. Adapt the language and focus to the healthcare audience implied \
by the event (e.g., nurses, community health workers, outreach teams, HR staff). \
Highlight mission alignment and community impact. No product mentions.

Respond with valid JSON only, no extra fields, exactly this shape:
{{
  "page_title": "...",
  "intro_copy": "...",
  "description": ["...", "..."]
}}"""


# ── Exceptions ────────────────────────────────────────────────────────────────

class CopyGenerationError(Exception):
    """Raised when copy cannot be generated or parsed from the API response."""


# ── Internal helpers ──────────────────────────────────────────────────────────

def _build_prompt(event_name: str, slug: str, notes: str = "") -> str:
    notes_block = f"\nAdditional instructions: {notes}" if notes.strip() else ""
    return _USER_TEMPLATE.format(event_name=event_name, slug=slug, notes_block=notes_block)


def _parse_response(raw: str) -> dict:
    """
    Extract and validate the JSON payload from the model response.

    Raises:
        CopyGenerationError: if JSON is missing, malformed, or has wrong shape.
    """
    # Strip markdown code fences if the model wraps the JSON
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise CopyGenerationError(
            f"Model returned non-JSON response: {exc}\nRaw: {raw!r}"
        ) from exc

    _ALLOWED_KEYS = {"page_title", "intro_copy", "description"}
    extra_keys = set(data.keys()) - _ALLOWED_KEYS
    if extra_keys:
        raise CopyGenerationError(
            f"Response contains unexpected fields {sorted(extra_keys)!r}: {data!r}"
        )

    if not isinstance(data.get("page_title"), str) or not data["page_title"].strip():
        raise CopyGenerationError(
            f"Missing or invalid 'page_title' in response: {data!r}"
        )
    if not isinstance(data.get("intro_copy"), str) or not data["intro_copy"].strip():
        raise CopyGenerationError(
            f"Missing or invalid 'intro_copy' in response: {data!r}"
        )
    if (
        not isinstance(data.get("description"), list)
        or not data["description"]
        or not all(isinstance(s, str) and s.strip() for s in data["description"])
    ):
        raise CopyGenerationError(
            f"Missing or invalid 'description' in response: {data!r}"
        )

    return {
        "page_title":  data["page_title"].strip(),
        "intro_copy":  data["intro_copy"].strip(),
        "description": [s.strip() for s in data["description"]],
    }


# ── Public API ────────────────────────────────────────────────────────────────

def generate_copy(event_name: str, slug: str, notes: str = "") -> dict:
    """
    Generate intro_copy and description for a campaign using the Claude API.

    Args:
        event_name: Human-readable event name (col B from LOOKBOOKS_MASTER).
        slug:       Campaign slug (col C from LOOKBOOKS_MASTER).

    Returns:
        {
            "intro_copy":  str,          # 1–2 sentences
            "description": list[str],    # 2–3 sentences
        }

    Raises:
        CopyGenerationError: if the API call fails or the response is malformed.

    Note:
        - page_title is NOT generated here (verbatim from sheet).
        - CTA fields are NOT generated here (verbatim from sheet).
        - No sheet values are read or written by this function.
        - No product data is accessed or modified.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise CopyGenerationError(
            "ANTHROPIC_API_KEY is not set in the environment."
        )

    client = Anthropic(api_key=api_key, max_retries=2, timeout=60.0)
    prompt = _build_prompt(event_name=event_name, slug=slug, notes=notes)

    logger.info("Generating copy for event=%r slug=%r", event_name, slug)

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception as exc:
        raise CopyGenerationError(
            f"Anthropic API call failed: {exc}"
        ) from exc

    raw = response.content[0].text
    result = _parse_response(raw)

    logger.info(
        "Copy generated: intro_copy=%d chars  description=%d sentences",
        len(result["intro_copy"]),
        len(result["description"]),
    )
    return result
