"""
Turn daily_news.json into structured slide copy for 3 Instagram carousels, using
Google Gemini 2.5 Flash (free tier via Google AI Studio) with structured outputs.
Gemini picks the 3 most engaging stories and writes the copy for each 7-slide arc;
the layout is rendered deterministically by generate_carousels.py (the model never
emits HTML).

Requires GEMINI_API_KEY in the environment (get a free key at
https://aistudio.google.com/app/apikey).  Run:  python write_carousels.py
"""
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from typing import List

from google import genai
from google.genai import types
from pydantic import BaseModel

BASE = Path(__file__).parent
NEWS = BASE / "daily_news.json"
OUT = BASE / "carousel_content.json"
MODEL = "gemini-2.5-flash"


# ---------------------------------------------------------------- output schema
class Breakdown(BaseModel):
    heading: str              # short slide heading (a few words)
    body: str                 # one idea, max 30 words


class Carousel(BaseModel):
    slug: str                 # short kebab id for the story, e.g. "dscr-tightening"
    title: str                # short internal title (used for the email subject)
    source: str               # news outlet the story came from, e.g. "HousingWire", "Inman"
    source_url: str           # exact link of the article this carousel is based on (the `link:` value)
    cover_text: str           # cover overlay, MAX 8 words, punchy
    caption: str              # 100-150 words; the FIRST line must stand alone as a hook
    hashtags: List[str]       # exactly 6, mixing industry + reach tags
    # Slide 1 — Hook / cover (light)
    hook_tag: str             # 2-3 word category label
    hook: str                 # bold claim or question reframing the story, MAX 12 words
    # Slide 2 — What happened (dark)
    what_happened_heading: str
    what_happened: str        # the news in exactly 2 plain sentences
    # Slides 3-6 — The breakdown (one idea per slide)
    breakdown: List[Breakdown]  # EXACTLY 4
    # Slide 7 — My take (gradient) — the contrarian, screenshot slide
    my_take_heading: str
    my_take: str              # the non-obvious angle, quotable
    # Slide 8 — What to do (light)
    action_lo: str            # one concrete move for loan officers
    action_realtor: str       # one concrete move for realtors
    # Slide 9 — CTA (gradient)
    cta_question: str         # ONE sharp question inviting executives to comment


class Output(BaseModel):
    carousels: List[Carousel]  # exactly 3


SYSTEM = """ROLE
You are a 20-year mortgage veteran: 10 years as a producing loan officer, 10 years as an \
underwriter. You've originated the loans AND decided which ones live or die. This dual lens \
is your signature — you don't just report mortgage news, you explain what it means at the \
file level, the pipeline level, and the P&L level.

TASK
From the day's mortgage/housing headlines below, pick the THREE stories with the strongest, \
most non-obvious takes for an industry audience and turn each into an Instagram carousel \
script. Return exactly 3 carousels.

AUDIENCE
Mortgage executives, high-level loan officers, and top-producing realtors. They're smart and \
busy — but write at a 10th-grade reading level anyway. Short sentences. Any industry term gets \
a plain-English translation in parentheses the first time it appears, e.g., "DTI (how much of \
your income goes to debt)."

POSITIONING RULES
1. Never summarize the news like a reporter. Lead with what everyone else missed or got wrong.
2. Use the underwriter lens as the differentiator at least once per carousel: "Here's what this \
actually changes when a file hits underwriting..."
3. Confident, direct, zero clickbait. No "You WON'T believe this." The hook earns attention with \
insight, not hype.
4. Write like a sharp colleague talking at a bar after a conference — not a compliance memo, not \
a LinkedIn influencer.

FILL THESE FIELDS FOR EACH CAROUSEL (they map to a 9-slide carousel):
- cover_text: the cover overlay, MAX 8 words, punchy.
- hook: slide 1 — one bold claim or question that reframes the story, MAX 12 words.
- hook_tag: a 2-3 word category label.
- what_happened_heading + what_happened: slide 2 — the news in EXACTLY 2 plain sentences.
- breakdown: slides 3-6 — EXACTLY 4 items, each {heading, body}. One idea per slide, body MAX 30 \
words. Build the argument step by step, using the underwriter lens at least once.
- my_take_heading + my_take: slide 7 — the contrarian or non-obvious angle. This is the screenshot \
slide, so make my_take quotable.
- action_lo + action_realtor: slide 8 — one concrete move for loan officers, one for realtors.
- cta_question: slide 9 — ONE sharp question that invites executives to comment. Never "follow for more".
- caption: 100-150 words. The FIRST line must work as a standalone hook (it gets cut off in feed).
- hashtags: EXACTLY 6, mixing industry (e.g. #mortgageindustry) and reach (e.g. #realestateagent). \
Do not include #MortgageIntelligenceDaily (it is added automatically).
- source + source_url: the outlet name and the EXACT article link (the `link:` value) this carousel \
is based on.

HARD RULES
- Use ONLY numbers and facts from the provided reporting. Never add outside statistics. If context \
is needed that the source doesn't provide, write "[VERIFY: ...]" inline so it can be fact-checked.
- No rate quotes, no guarantees, no "now is the best time to buy." Educational framing only.
- Prefer stories that genuinely support a strong take. If a headline only supports a weak take, pick \
a different one — you must still return 3 carousels, each with a real, earned insight.
- Plain text only — no HTML, no markdown."""


def clean(text):
    text = re.sub(r"<[^>]+>", "", text or "")
    return re.sub(r"\s+", " ", text).strip()


def shorten_url(url):
    """Shorten a URL with TinyURL's free, tokenless endpoint (no account, no
    monthly cap). is.gd was tried first but returns 'database insert failed' on
    many real news domains, so TinyURL is the reliable free choice. Any failure
    falls back to the original long URL."""
    url = (url or "").strip()
    if not url:
        return url
    try:
        api = "https://tinyurl.com/api-create.php?url=" + urllib.parse.quote(url, safe="")
        req = urllib.request.Request(api, headers={"User-Agent": "Mozilla/5.0 (MortgageIntelligenceDaily bot)"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            short = resp.read().decode("utf-8").strip()
        if short.startswith("http"):
            return short
        print(f"TinyURL returned {short!r}; using the full URL.")
        return url
    except Exception as exc:  # noqa: BLE001 — never let link-shortening break the run
        print(f"TinyURL shorten failed ({exc}); using the full URL.")
        return url


def _split_trailing_hashtags(caption):
    """Split a caption into (body, [hashtags]) by peeling off the trailing run
    of hashtags, so they can be regrouped in one block."""
    caption = (caption or "").strip()
    m = re.search(r"((?:#\w+\s*)+)$", caption)
    if not m:
        return caption, []
    tags = re.findall(r"#\w+", m.group(1))
    return caption[:m.start()].rstrip(), tags


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

    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        sys.exit("GEMINI_API_KEY not set. Get a free key at "
                 "https://aistudio.google.com/app/apikey")

    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=MODEL,
        contents=(
            f"Today's mortgage and housing headlines:\n\n{news_block}\n\n"
            "Pick the 3 most engaging stories for prospective home buyers and write "
            "all three carousels."
        ),
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM,
            response_mime_type="application/json",
            response_schema=Output,
            max_output_tokens=8192,
            thinking_config=types.ThinkingConfig(thinking_budget=0),
        ),
    )

    # response.parsed is an Output instance when response_schema is a Pydantic model;
    # fall back to parsing the raw JSON text if the SDK didn't hydrate it.
    result = response.parsed
    if result is None:
        result = Output.model_validate_json(response.text)

    # Rebuild each caption as: body, then the article link, then ALL hashtags in
    # one grouped block (the model's 6 tags + any inline tags + the brand hashtag).
    BRAND_TAG = "#MortgageIntelligenceDaily"
    for c in result.carousels:
        body, inline_tags = _split_trailing_hashtags(c.caption)
        seen, tags = set(), []
        for t in list(c.hashtags) + inline_tags + [BRAND_TAG]:
            t = t.strip()
            if not t:
                continue
            if not t.startswith("#"):
                t = "#" + t
            if t.lower() not in seen:
                seen.add(t.lower())
                tags.append(t)
        link = shorten_url(c.source_url)
        # Tail block: the shortened article link, then all hashtags on the next line.
        tail = []
        if link:
            tail.append(f"Source : {link}")
        if tags:
            tail.append(" ".join(tags))
        parts = [body]
        if tail:
            parts.append("\n".join(tail))
        c.caption = "\n\n".join(p for p in parts if p.strip())

    OUT.write_text(json.dumps(result.model_dump(), indent=2), encoding="utf-8")
    print(f"Wrote {OUT.name}: {len(result.carousels)} carousels")
    for c in result.carousels:
        print(f"  - {c.title}")


if __name__ == "__main__":
    main()
