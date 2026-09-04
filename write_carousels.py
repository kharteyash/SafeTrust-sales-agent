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
import urllib.error
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
# Retired models 404 with "update your code to use models/<replacement>" — that
# replacement is parsed and queued automatically, so this list self-heals; still,
# keep it current (the 2.x family was retired in Aug 2026).
MODELS = [
    "gemini-3.6-flash",
    "gemini-3.5-flash-lite",
    "gemini-2.5-flash",
]

# Substrings that mark a transient/availability error worth retrying or failing over.
_TRANSIENT = ("503", "overloaded", "unavailable", "429", "resource_exhausted",
              "500", "internal", "deadline", "timeout")

# Fallback providers when every Gemini model fails, tried in order: Groq (free
# tier), then Cerebras, then xAI (Grok), then SambaNova Cloud. All are
# OpenAI-compatible (JSON mode) and read their API keys from the environment —
# never hardcode a key. Providers whose account has no credit fail over cleanly.
FALLBACK_PROVIDERS = [
    {
        "name": "Groq",
        "url": "https://api.groq.com/openai/v1/chat/completions",
        "key_env": "GROQ_API_KEY",
        # Groq retired its Llama models in Aug 2026 — these are the current ones.
        "models": ["openai/gpt-oss-120b", "qwen/qwen3.6-27b", "openai/gpt-oss-20b"],
        # Free tier rejects any request where input + max_tokens > 8000 (413),
        # so requests are pre-sized to fit.
        "req_cap": 8000,
    },
    {
        "name": "Cerebras",
        "url": "https://api.cerebras.ai/v1/chat/completions",
        "key_env": "CEREBRAS_API_KEY",
        "models": ["gpt-oss-120b", "zai-glm-4.7", "gemma-4-31b"],
    },
    {
        "name": "xAI",
        "url": "https://api.x.ai/v1/chat/completions",
        "key_env": "XAI_API_KEY",
        # Unknown model ids just fail over to the next entry, so newer-first is safe.
        "models": ["grok-4-1-fast-non-reasoning", "grok-4-fast-non-reasoning", "grok-3-mini"],
    },
    {
        "name": "SambaNova",
        "url": "https://api.sambanova.ai/v1/chat/completions",
        "key_env": "SAMBANOVA_API_KEY",
        "models": ["Meta-Llama-3.3-70B-Instruct", "DeepSeek-V3.2"],
    },
]


class _RawResponse:
    """Mimics the google-genai response shape the call sites expect: `.parsed` is
    None (so they fall back to `.text`) and `.text` holds the raw JSON string."""
    def __init__(self, text):
        self.parsed = None
        self.text = text


def _shrink_contents(contents, limit=6500):
    """Cut a newline-separated payload (the headlines list) at an item boundary so
    it fits a free tier's per-request token cap. Single-line payloads (the compact
    JSON sent for translation) are returned unchanged — cutting would corrupt them."""
    if len(contents) <= limit:
        return contents
    cut = contents.rfind("\n", 0, limit)
    if cut < limit // 2:
        return contents
    return contents[:cut] + "\n[additional headlines omitted for length]"


def _fallback_generate(contents, system_instruction, response_schema, max_output_tokens):
    """Last-resort generation via the OpenAI-compatible FALLBACK_PROVIDERS, in order.
    Returns a _RawResponse with JSON text, or None if no provider has a key set or
    every model of every keyed provider fails."""
    schema = json.dumps(response_schema.model_json_schema())
    sys_msg = (f"{system_instruction}\n\nReturn ONLY a single JSON object that strictly conforms "
               f"to this JSON schema — include every required field, no markdown, no code fences, "
               f"no commentary:\n{schema}")
    last_exc = None
    for provider in FALLBACK_PROVIDERS:
        key = os.environ.get(provider["key_env"])
        if not key:
            print(f"{provider['name']}: no {provider['key_env']} set — skipping.")
            continue
        cap = provider.get("req_cap")
        for model in provider["models"]:
            mt = max_output_tokens
            cont = contents
            if cap:
                # Pre-size to the provider's per-request cap: leave the model a
                # real completion budget, trimming the headline list if needed.
                # (chars/4 slightly overestimates tokens — a safety margin.)
                budget = cap - 200 - (len(sys_msg) + len(cont)) // 4
                if budget < 4500:
                    cont = _shrink_contents(contents, 3800)
                    budget = cap - 200 - (len(sys_msg) + len(cont)) // 4
                mt = max(2500, min(mt, budget))
            for attempt in (1, 2, 3):
                payload = {
                    "model": model,
                    "messages": [{"role": "system", "content": sys_msg},
                                 {"role": "user", "content": cont}],
                    "response_format": {"type": "json_object"},
                    "max_tokens": mt,
                    "temperature": 0.4,
                }
                if "gpt-oss" in model:
                    # Reasoning burns completion budget the JSON needs.
                    payload["reasoning_effort"] = "low"
                body = json.dumps(payload).encode("utf-8")
                req = urllib.request.Request(
                    provider["url"], data=body, method="POST",
                    headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                             # Cloudflare fronts these APIs and rejects Python's
                             # default urllib UA with error 1010 — send a real UA.
                             "User-Agent": "Mozilla/5.0 (MortgageIntelligenceDaily bot)"})
                try:
                    with urllib.request.urlopen(req, timeout=120) as resp:
                        data = json.loads(resp.read())
                    text = data["choices"][0]["message"]["content"].strip()
                    if text.startswith("```"):  # strip accidental code fences
                        text = text[text.find("{"):text.rfind("}") + 1]
                    # Validate here so truncated/malformed JSON tries the next
                    # model instead of crashing the run later.
                    response_schema.model_validate_json(text)
                    print(f"{provider['name']}: generated with {model}")
                    return _RawResponse(text)
                except urllib.error.HTTPError as exc:
                    last_exc = exc
                    try:
                        detail = exc.read().decode("utf-8", "replace")[:200]
                    except Exception:  # noqa: BLE001 — body may be unreadable
                        detail = ""
                    # Free-tier per-request caps count input AND max_tokens (Groq:
                    # 8000/request) — shrink the headline list and size the
                    # completion budget to what fits, then retry.
                    if exc.code == 413 and attempt == 1:
                        cont = _shrink_contents(contents)
                        est_input = (len(sys_msg) + len(cont)) // 4 + 200
                        mt = max(2500, min(mt, 7800 - est_input))
                        print(f"{provider['name']} model {model} payload too large (413) — "
                              f"retrying with max_tokens={mt} and "
                              f"{len(cont)}/{len(contents)} chars of input.")
                        continue
                    # Free tiers rate-limit per minute; two back-to-back calls
                    # (generate, then translate) trip this — wait and retry.
                    if exc.code == 429 and attempt < 3:
                        try:
                            wait = min(int(float(exc.headers.get("Retry-After", 45))), 90)
                        except (TypeError, ValueError):
                            wait = 45
                        print(f"{provider['name']} model {model} rate-limited (429) — "
                              f"retrying in {wait}s.")
                        time.sleep(wait)
                        continue
                    print(f"{provider['name']} model {model} failed: "
                          f"HTTP {exc.code} {detail}")
                    break
                except Exception as exc:  # noqa: BLE001 — try the next model/provider
                    last_exc = exc
                    print(f"{provider['name']} model {model} failed: {str(exc)[:160]}")
                    break
    print(f"Fallback providers exhausted. Last error: {last_exc}")
    return None


def generate_with_fallback(client, contents, *, system_instruction, response_schema,
                           max_output_tokens=8192, models=None, attempts_per_model=3,
                           base_delay=6):
    """Call Gemini, trying each model in MODELS until one succeeds. Each model gets
    retries on transient errors (6am ET demand spikes 503 for a minute or two)
    before moving on. When a retired model's 404 names its replacement, that model
    is queued and tried too, so retirements never kill the run. thinking_budget=0
    is only sent to the 2.5 "thinking" family (older models reject it). Raises if
    all fail."""
    models = list(models or MODELS)
    tried = set()
    last_exc = None
    for model in models:  # appends during iteration are picked up by the loop
        if model in tried:
            continue
        tried.add(model)
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
                # A retired model's 404 names its successor ("update your code to
                # use models/<id>") — queue that model so retirements self-heal.
                repl = re.search(r"use models/([\w.\-]+)", str(exc))
                if repl and repl.group(1) not in tried and repl.group(1) not in models:
                    print(f"Gemini suggests replacement model {repl.group(1)} — queueing it.")
                    models.append(repl.group(1))
                transient = any(s in msg for s in _TRANSIENT)
                if transient and attempt < attempts_per_model:
                    time.sleep(base_delay * attempt)
                    continue
                break  # non-transient, or out of attempts for this model — try the next

    # Every Gemini model failed — last resort: xAI, then SambaNova (keyed via env).
    print("All Gemini models failed — falling back to xAI/SambaNova.")
    fb = _fallback_generate(contents, system_instruction, response_schema, max_output_tokens)
    if fb is not None:
        return fb
    raise RuntimeError(f"All Gemini models failed ({', '.join(models)}) and every "
                       f"fallback provider was unavailable. Last Gemini error: {last_exc}")


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


TRANSLATE_SYSTEM = """You are a professional English-to-Spanish translator for \
QuieroUnaCasa.com, the Spanish-language brand of a U.S. mortgage company.

TASK
Translate the given Instagram carousel scripts (JSON) into Spanish.

RULES
- Formal Spanish: always address the reader as "usted", never "tu". Neutral Latin \
American business Spanish — no regional slang.
- 10th-grade reading level: short sentences, plain everyday words, no bureaucratic phrasing.
- Keep slug, source, source_url and hashtags EXACTLY as given — never translate or alter them.
- Keep all numbers, percentages, dollar figures and program names (FHA, VA, DSCR, HELOC, \
Non-QM...) unchanged. Where the English industry term is standard in the U.S. market, keep \
it in parentheses after the Spanish the first time, e.g. "linea de credito con garantia \
hipotecaria (HELOC)".
- GLOSSARY: translate "underwriter" as "asesor" — NEVER "suscriptor" (it reads as \
"subscriber" to Spanish speakers).
- Respect the same field limits as the original: cover_text MAX 8 words; hook MAX 12 words; \
what_happened EXACTLY 2 sentences; each breakdown body MAX 30 words; caption 100-150 words \
whose FIRST line stands alone as a hook.
- my_take: MAX 45 words in Spanish — tighten the wording if the English runs longer; it must \
fit on one slide.
- my_take_heading: never start it with "Mi Opinion:" or similar — the slide already carries \
that label.
- Headings stay in sentence case — NEVER ALL CAPS, and never a generic label like \
"Lo que sucedio" as a heading.
- Translate the meaning, not word-for-word — the result must read like it was written in \
Spanish by a mortgage professional.
- Return the same JSON structure with exactly 3 carousels in the same order.
- Plain text only — no HTML, no markdown."""


def _actually_spanish(en, es):
    """Guard against a model echoing the input untranslated: titles must differ
    and the copy must contain everyday Spanish words."""
    same = sum(1 for a, b in zip(en, es)
               if a.title.strip().lower() == b.title.strip().lower())
    if same >= 2:
        return False
    text = " ".join(f"{c.caption} {c.what_happened} {c.my_take}" for c in es).lower()
    return any(w in text for w in (" de ", " la ", " el ", " que ", " los ",
                                   " una ", " para ", "cion", "ción"))


def translate_carousels(client, carousels):
    """Translate the English carousels into formal Spanish (usted, 10th-grade level).
    Returns a list of Carousel or [] if translation fails — the Spanish set is
    optional and must never break the English run."""
    # Compact JSON — free-tier fallbacks (Groq) reject large requests with 413,
    # and indentation alone roughly doubles the token count of the payload.
    payload = json.dumps({"carousels": [c.model_dump() for c in carousels]},
                         ensure_ascii=False, separators=(",", ":"))
    contents = f"Translate these carousels into Spanish:\n\n{payload}"
    for attempt in (1, 2):
        try:
            resp = generate_with_fallback(
                client,
                contents=contents,
                system_instruction=TRANSLATE_SYSTEM,
                response_schema=Output,
                max_output_tokens=8192,
            )
            parsed = resp.parsed
            if parsed is None:
                parsed = Output.model_validate_json(resp.text)
            es = parsed.carousels
            if len(es) != len(carousels):
                raise ValueError(f"expected {len(carousels)} translated carousels, got {len(es)}")
            # Pin the fields translation must never touch.
            for en, s in zip(carousels, es):
                s.slug, s.source, s.source_url = en.slug, en.source, en.source_url
                s.hashtags = list(en.hashtags)
            if _actually_spanish(carousels, es):
                return es
            print(f"Translation attempt {attempt} came back untranslated — retrying.")
            contents = ("IMPORTANT: the previous attempt returned the text UNTRANSLATED. "
                        "Every field value MUST be rewritten in Spanish.\n\n" + contents)
        except Exception as exc:  # noqa: BLE001 — Spanish is best-effort
            print(f"Spanish translation attempt {attempt} failed ({str(exc)[:200]})")
    print("Spanish translation failed — continuing with English only.")
    return []


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
- HEADING STYLE: every heading (what_happened_heading, breakdown headings, my_take_heading, \
cover_text) is written in sentence case — NEVER ALL CAPS. Headings must be specific to the \
story; never reuse the slide's own label ("What Happened", "My Take", "The Breakdown") as \
the heading text.
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


def _finalize_captions(carousels, link_cache, source_label="Source"):
    """Rebuild each caption as: body, then the article link, then EXACTLY 5 hashtags
    in one grouped block: the 2 permanent brand tags first, then the model's
    3 dynamic story tags (inline caption tags fill in if the model returned <3).
    link_cache dedupes TinyURL calls when both languages share an article."""
    PERMANENT_TAGS = ["#SafetrustMortgage", "#MortgageIntelligenceDaily"]
    MAX_TAGS = 5
    for c in carousels:
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
        if c.source_url not in link_cache:
            link_cache[c.source_url] = shorten_url(c.source_url)
        link = link_cache[c.source_url]
        # Tail block: the shortened article link, then all hashtags on the next line.
        tail = []
        if link:
            tail.append(f"{source_label} : {link}")
        if tags:
            tail.append(" ".join(tags))
        parts = [body]
        if tail:
            parts.append("\n".join(tail))
        c.caption = "\n\n".join(p for p in parts if p.strip())


def _client():
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        sys.exit("GEMINI_API_KEY not set. Get a free key at "
                 "https://aistudio.google.com/app/apikey")
    return genai.Client(api_key=api_key)


def _strip_caption_tail(caption):
    """Undo _finalize_captions: drop the 'Source : link' / hashtag tail so a
    finalized caption can be re-translated cleanly."""
    body = (caption or "").split("\n\nSource :")[0].split("\n\nFuente :")[0]
    body, _ = _split_trailing_hashtags(body)
    return body.strip()


def generate_english():
    """Scraped news -> 3 English carousels in carousel_content.json."""
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

    response = generate_with_fallback(
        _client(),
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

    _finalize_captions(result.carousels, {}, source_label="Source")
    # A fresh English set invalidates any previous day's translation.
    OUT.write_text(json.dumps(result.model_dump(), indent=2, ensure_ascii=False),
                   encoding="utf-8")
    print(f"Wrote {OUT.name}: {len(result.carousels)} English carousels")
    for c in result.carousels:
        print(f"  - {c.title}")
    return result.carousels


def generate_spanish():
    """Translate the English carousels already in carousel_content.json and add
    them to the file as carousels_es. Exits non-zero if translation fails so
    the Spanish workflow retries later."""
    if not OUT.exists():
        sys.exit("carousel_content.json not found — the English run must happen first.")
    data = json.loads(OUT.read_text(encoding="utf-8"))
    en = [Carousel.model_validate(c) for c in data.get("carousels", [])]
    if not en:
        sys.exit("carousel_content.json has no English carousels.")
    # Strip the link/hashtag tails before translating; they're rebuilt after.
    for c in en:
        c.caption = _strip_caption_tail(c.caption)

    es_carousels = translate_carousels(_client(), en)
    if not es_carousels:
        sys.exit("Spanish translation failed on every provider — try again later.")
    _finalize_captions(es_carousels, {}, source_label="Fuente")

    data["carousels_es"] = [c.model_dump() for c in es_carousels]
    OUT.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {OUT.name}: {len(es_carousels)} Spanish carousels added")
    for c in es_carousels:
        print(f"  - {c.title}")


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"
    if mode == "en":
        generate_english()
    elif mode == "es":
        generate_spanish()
    else:  # "all": legacy single-run behaviour
        generate_english()
        generate_spanish()


if __name__ == "__main__":
    main()
