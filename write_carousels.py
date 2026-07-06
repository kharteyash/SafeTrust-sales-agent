"""
Turn daily_news.json into structured slide copy for 3 Instagram carousels, using
Claude with structured outputs. Claude picks the 3 most engaging stories and
writes the copy for each 7-slide arc; the layout is rendered deterministically by
generate_carousels.py (Claude never emits HTML).

Requires ANTHROPIC_API_KEY in the environment. Run:  python write_carousels.py
"""
import json
import re
import sys
from pathlib import Path
from typing import List

import anthropic
from pydantic import BaseModel

BASE = Path(__file__).parent
NEWS = BASE / "daily_news.json"
OUT = BASE / "carousel_content.json"
MODEL = "claude-opus-4-8"


# ---------------------------------------------------------------- output schema
class Feature(BaseModel):
    label: str
    desc: str


class Step(BaseModel):
    title: str
    desc: str


class Carousel(BaseModel):
    slug: str                 # short kebab id for the story, e.g. "rates-rising"
    title: str                # internal title (not shown on slides)
    caption: str              # Instagram caption; may end with a single emoji
    # Slide 1 — Hero (light)
    hero_tag: str             # short uppercase category label
    hero_stat: str            # a big number like "74%" ONLY if the story leads with one, else ""
    hero_heading: str         # bold scroll-stopping hook, plain text (no HTML)
    hero_sub: str             # one supporting sentence
    # Slide 2 — Problem / tension (dark)
    problem_tag: str
    problem_heading: str
    problem_sub: str
    problem_label: str        # tiny label above the pills, e.g. "What everyone assumed:"
    problem_pills: List[str]  # 3 short strike-through phrases (what's outdated/wrong)
    # Slide 3 — Solution / key insight (brand gradient)
    solution_tag: str
    solution_heading: str
    solution_sub: str
    quote_label: str          # tiny uppercase label above the quote
    quote: str                # one punchy takeaway sentence (no surrounding quotes)
    # Slide 4 — Features / the facts (light)
    features_tag: str
    features_heading: str
    features: List[Feature]   # exactly 4
    # Slide 5 — Details / why it matters (dark)
    details_tag: str
    details_heading: str
    details_sub: str
    details_pills: List[str]  # 3-4 short tag phrases
    # Slide 6 — How-to steps (light)
    howto_tag: str
    howto_heading: str
    steps: List[Step]         # exactly 4, numbered 01-04 by the renderer
    # Slide 7 — CTA (brand gradient)
    cta_tag: str              # a theme tag, NOT the brand name
    cta_heading: str          # call to action
    cta_sub: str
    cta_button: str           # short button label, may end with an arrow


class Output(BaseModel):
    carousels: List[Carousel]  # exactly 3


SYSTEM = """You write Instagram carousel copy for SafeTrust Mortgage, a trustworthy \
mortgage lender. The audience is prospective and current home buyers (consumers, not \
industry insiders).

From the day's mortgage/housing headlines, pick the THREE most engaging stories for \
that audience — scroll-stopping, relatable, shareable, and useful. Skip pure B2B / \
industry-politics stories (lender rankings, trade-org renames, antitrust procedure). \
Write one carousel per chosen story. Return exactly 3 carousels.

Each carousel follows this fixed 7-slide arc — fill the fields for all seven:
 1 Hero      — a bold hook that stops the scroll (a value proposition or surprising claim).
 2 Problem   — the tension, myth, or pain point, with 3 strike-through pills of what's outdated.
 3 Solution  — the key insight that resolves it, plus one quotable takeaway line.
 4 Features  — exactly 4 concrete facts/benefits (label + short description each).
 5 Details   — why it matters, with 3-4 short tag pills.
 6 How-to    — exactly 4 practical steps (title + short description each).
 7 CTA       — a call to action driving toward pre-approval / getting today's rate / talking to SafeTrust.

Voice: professional, clear, warm, credible — never hypey or clickbait. Tags are SHORT \
and UPPERCASE-style (2-4 words). Headings are punchy and concrete. Body lines are one \
sentence. Plain text only — no HTML, no markdown, no emoji except a single optional one \
at the end of each caption.

Grounding: base every carousel on the actual reporting provided. Use the real figures \
that appear in the summaries (rates, percentages, dates) when relevant. NEVER invent \
statistics, quotes, or numbers that aren't supported by the source. Set hero_stat only \
when the story genuinely leads with a single striking number (like a survey percentage); \
otherwise leave hero_stat as an empty string.

The CTA tag must be a theme (e.g. "LET'S TALK RATES", "YOUR NEXT MOVE", "MAKE IT YOURS") \
— never just the brand name, since the brand already appears on the slide."""


def clean(text):
    text = re.sub(r"<[^>]+>", "", text or "")
    return re.sub(r"\s+", " ", text).strip()


def main():
    if not NEWS.exists():
        sys.exit("daily_news.json not found — run scrape.py first.")
    items = json.loads(NEWS.read_text(encoding="utf-8"))
    if not items:
        sys.exit("daily_news.json is empty — no stories to work with today.")

    lines = []
    for i, entry in enumerate(items):
        summary = clean(entry.get("summary", ""))[:400]
        lines.append(f"{i + 1}. {entry.get('title', '').strip()}\n"
                     f"   {summary}\n"
                     f"   link: {entry.get('link', '')}")
    news_block = "\n".join(lines)

    client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from the environment
    response = client.messages.parse(
        model=MODEL,
        max_tokens=16000,
        system=SYSTEM,
        messages=[{
            "role": "user",
            "content": (
                f"Today's mortgage and housing headlines:\n\n{news_block}\n\n"
                "Pick the 3 most engaging stories for prospective home buyers and write "
                "all three carousels."
            ),
        }],
        output_format=Output,
    )

    result = response.parsed_output
    OUT.write_text(json.dumps(result.model_dump(), indent=2), encoding="utf-8")
    print(f"Wrote {OUT.name}: {len(result.carousels)} carousels")
    for c in result.carousels:
        print(f"  - {c.title}")


if __name__ == "__main__":
    main()
