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
import time
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

# Try these Gemini models in order — if one is overloaded/unavailable (e.g. a 503
# "model is overloaded" under heavy traffic), fall through to the next until one works.
MODELS = [
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite",
]

# Substrings that mark a transient/availability error worth retrying or failing over.
_TRANSIENT = ("503", "overloaded", "unavailable", "429", "resource_exhausted",
              "500", "internal", "deadline", "timeout")

# Last-resort provider when every Gemini model fails: SambaNova Cloud (OpenAI-compatible,
# JSON mode). Reads SAMBANOVA_API_KEY from the environment — never hardcode the key.
SAMBANOVA_URL = "https://api.sambanova.ai/v1/chat/completions"
SAMBANOVA_MODELS = ["Meta-Llama-3.3-70B-Instruct", "DeepSeek-V3.2"]


class _RawResponse:
    """Mimics the google-genai response shape the call sites expect: `.parsed` is
    None (so they fall back to `.text`) and `.text` holds the raw JSON string."""
    def __init__(self, text):
        self.parsed = None
        self.text = text


def _sambanova_generate(contents, system_instruction, response_schema, max_output_tokens):
    """Last-resort generation via SambaNova. Returns a _RawResponse with JSON text,
    or None if no key is set or every SambaNova model fails."""
    key = os.environ.get("SAMBANOVA_API_KEY")
    if not key:
        return None
    schema = json.dumps(response_schema.model_json_schema())
    sys_msg = (f"{system_instruction}\n\nReturn ONLY a single JSON object that strictly conforms "
               f"to this JSON schema — include every required field, no markdown, no code fences, "
               f"no commentary:\n{schema}")
    last_exc = None
    for model in SAMBANOVA_MODELS:
        body = json.dumps({
            "model": model,
            "messages": [{"role": "system", "content": sys_msg},
                         {"role": "user", "content": contents}],
            "response_format": {"type": "json_object"},
            "max_tokens": max_output_tokens,
            "temperature": 0.4,
        }).encode("utf-8")
        req = urllib.request.Request(
            SAMBANOVA_URL, data=body, method="POST",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = json.loads(resp.read())
            text = data["choices"][0]["message"]["content"].strip()
            if text.startswith("```"):  # strip accidental code fences
                text = text[text.find("{"):text.rfind("}") + 1]
            print(f"SambaNova: generated with {model}")
            return _RawResponse(text)
        except Exception as exc:  # noqa: BLE001 — try the next SambaNova model
            last_exc = exc
            print(f"SambaNova model {model} failed: {str(exc)[:160]}")
    print(f"SambaNova fallback exhausted. Last error: {last_exc}")
    return None


def generate_with_fallback(client, contents, *, system_instruction, response_schema,
                           max_output_tokens=8192, models=None, attempts_per_model=2,
                           base_delay=3):
    """Call Gemini, trying each model in MODELS until one succeeds. Each model gets a
    quick retry on transient errors before moving on. thinking_budget=0 is only sent
    to the 2.5 "thinking" family (older models reject it). Raises if all fail."""
    models = models or MODELS
    last_exc = None
    for model in models:
        cfg = dict(system_instruction=system_instruction,
                   response_mime_type="application/json",
                   response_schema=response_schema,
                   max_output_tokens=max_output_tokens)
        if model.startswith("gemini-2.5"):
            cfg["thinking_config"] = types.ThinkingConfig(thinking_budget=0)
        config = types.GenerateContentConfig(**cfg)
        for attempt in range(1, attempts_per_model + 1):
            try:
                resp = client.models.generate_content(model=model, contents=contents, config=config)
                print(f"Gemini: generated with {model}")
                return resp
            except Exception as exc:  # noqa: BLE001 — fail over across models
                last_exc = exc
                msg = str(exc).lower()
                print(f"Gemini model {model} attempt {attempt} failed: {str(exc)[:160]}")
                transient = any(s in msg for s in _TRANSIENT)
                if transient and attempt < attempts_per_model:
                    time.sleep(base_delay * attempt)
                    continue
                break  # non-transient, or out of attempts for this model — try the next

    # Every Gemini model failed — last resort: SambaNova (if SAMBANOVA_API_KEY set).
    print("All Gemini models failed — falling back to SambaNova.")
    sn = _sambanova_generate(contents, system_instruction, response_schema, max_output_tokens)
    if sn is not None:
        return sn
    raise RuntimeError(f"All Gemini models failed ({', '.join(models)}) and SambaNova "
                       f"fallback was unavailable. Last Gemini error: {last_exc}")


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
    hashtags: List[str]       # exactly 3, high-usage tags matched to the story
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
- hashtags: EXACTLY 3, each specific to THIS story's topic and chosen from established, high-usage \
tags on Instagram (e.g. #mortgagerates, #housingmarket, #realestateagent, #firsttimehomebuyer, \
#mortgagebroker, #loanofficer, #realestateinvesting, #homebuying) — pick the 3 with the best mix of \
topical fit and reach; never invent obscure tags. Do NOT include #SafetrustMortgage or \
#MortgageIntelligenceDaily (they are added automatically). Do not put hashtags inside the caption text.
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
    response = generate_with_fallback(
        client,
        contents=(
            f"Today's mortgage and housing headlines:\n\n{news_block}\n\n"
            "Pick the 3 most engaging stories for prospective home buyers and write "
            "all three carousels."
        ),
        system_instruction=SYSTEM,
        response_schema=Output,
        max_output_tokens=8192,
    )

    # response.parsed is an Output instance when response_schema is a Pydantic model;
    # fall back to parsing the raw JSON text if the SDK didn't hydrate it.
    result = response.parsed
    if result is None:
        result = Output.model_validate_json(response.text)

    # Rebuild each caption as: body, then the article link, then EXACTLY 5 hashtags
    # in one grouped block: the 2 permanent brand tags first, then the model's
    # 3 dynamic story tags (inline caption tags fill in if the model returned <3).
    PERMANENT_TAGS = ["#SafetrustMortgage", "#MortgageIntelligenceDaily"]
    MAX_TAGS = 5
    for c in result.carousels:
        body, inline_tags = _split_trailing_hashtags(c.caption)
        seen, tags = set(), []
        for t in PERMANENT_TAGS + list(c.hashtags) + inline_tags:
            t = t.strip()
            if not t:
                continue
            if not t.startswith("#"):
                t = "#" + t
            if t.lower() not in seen:
                seen.add(t.lower())
                tags.append(t)
        tags = tags[:MAX_TAGS]
        c.hashtags = tags
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
