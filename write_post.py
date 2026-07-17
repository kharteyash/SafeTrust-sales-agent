"""
Turn daily_news.json into a fun, bite-sized Instagram POST — "Kickoff News":
one graphic (headline + 2-3 quick news bites) plus a caption. Uses Google Gemini
2.5 Flash (free) with structured outputs. generate_post.py renders the image.

Separate product from the carousels.  Run:  python write_post.py
"""
import json
import os
import sys
from pathlib import Path
from typing import List

from google import genai
from google.genai import types
from pydantic import BaseModel

from write_carousels import clean, generate_with_fallback

BASE = Path(__file__).parent
NEWS = BASE / "daily_news.json"
OUT = BASE / "post_content.json"


# ---------------------------------------------------------------- output schema
class Item(BaseModel):
    emoji: str            # one leading emoji
    headline: str         # short, punchy, < 45 chars, no emoji inside
    line: str             # one plain-English sentence
    source: str           # outlet name


class Post(BaseModel):
    hook: str             # punny cover headline for the post, < 9 words
    items: List[Item]     # 2 or 3 bite-sized news items (prefer 3)
    caption: str          # fun IG caption, 60-120 words; first line stands alone as a hook
    hashtags: List[str]   # exactly 6, mixing industry + reach tags


SYSTEM = """You write "Kickoff News" — a fun, bite-sized daily mortgage & housing \
Instagram POST in the style of Sherwood's Snacks. Witty, punny, emoji-forward, useful. \
The audience is mixed: mortgage/real-estate pros AND regular homebuyers, so keep it \
accessible — briefly explain any jargon in plain English in parentheses the first time, \
e.g. "DTI (how much of your income goes to debt)."

From the day's headlines below, produce ONE post:
- hook: a punny/clever cover headline for the whole post, under 9 words, no emoji inside.
- items: pick the 2-3 most interesting stories. For each: a single emoji, a short punchy \
headline (under 45 characters, no emoji inside), one plain-English sentence explaining it \
with personality, and the outlet name in `source`. Prefer 3 items.
- caption: 60-120 words, fun and conversational. The FIRST line must work on its own as a \
hook (it gets cut off in feed).
- hashtags: exactly 6, mixing industry (e.g. #mortgageindustry) and reach (e.g. \
#realestate). Do NOT include #MortgageIntelligenceDaily (added automatically).

Voice: playful, sharp, clever wordplay, light humor — never hypey, never clickbait, never \
mean. Short sentences.

HARD RULES:
- Use ONLY facts and numbers that appear in the provided reporting. NEVER invent \
statistics, rates, or quotes.
- No rate quotes presented as offers, no financial advice, no "now is the best time to \
buy." Report the news with personality; don't sell.
- Plain text only in every field — no HTML, no markdown. Emojis only in the `emoji` \
fields."""


def main():
    if not NEWS.exists():
        sys.exit("daily_news.json not found — run scrape.py first.")
    items = json.loads(NEWS.read_text(encoding="utf-8"))
    if not items:
        sys.exit("daily_news.json is empty — no stories to work with today.")

    lines = []
    for i, entry in enumerate(items):
        summary = clean(entry.get("summary", ""))[:400]
        lines.append(f"{i + 1}. {entry.get('title', '').strip()}\n   {summary}\n"
                     f"   link: {entry.get('link', '')}")
    news_block = "\n".join(lines)

    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        sys.exit("GEMINI_API_KEY not set. Get a free key at "
                 "https://aistudio.google.com/app/apikey")

    client = genai.Client(api_key=api_key)
    response = generate_with_fallback(
        client,
        contents=(f"Today's mortgage and housing headlines:\n\n{news_block}\n\n"
                  "Write today's Kickoff News Instagram post."),
        system_instruction=SYSTEM,
        response_schema=Post,
        max_output_tokens=3072,
    )

    result = response.parsed
    if result is None:
        result = Post.model_validate_json(response.text)

    # Compose the caption: body, then all hashtags (model's 6 + brand) in one block.
    BRAND_TAG = "#MortgageIntelligenceDaily"
    seen, tags = set(), []
    for t in list(result.hashtags) + [BRAND_TAG]:
        t = t.strip()
        if t and not t.startswith("#"):
            t = "#" + t
        if t and t.lower() not in seen:
            seen.add(t.lower())
            tags.append(t)
    result.caption = (result.caption or "").rstrip() + "\n\n" + " ".join(tags)

    OUT.write_text(json.dumps(result.model_dump(), indent=2), encoding="utf-8")
    print(f"Wrote {OUT.name}: {len(result.items)} items")


if __name__ == "__main__":
    main()
