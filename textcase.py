"""
Capitalisation guard for model-written copy. Models occasionally return a
heading in ALL CAPS, or a whole story in lowercase; both are normalised here
before anything is rendered or emailed. Normal mixed-case text passes through
untouched (only its first letter is checked).
"""
import re

# Acronyms kept uppercase when a shouted heading is normalised to sentence case.
ACRONYMS = {"AI", "IA", "GSE", "GSES", "FHA", "VA", "USDA", "MLS", "DSCR", "HELOC",
            "ARM", "ARMS", "MBS", "LO", "LOS", "UWM", "CFPB", "HUD", "FED", "QM",
            "NON-QM", "DTI", "IRS", "US", "U.S.", "TNX", "US10Y", "APR", "PMI",
            "REIT", "ETF", "FHFA", "NAR", "ICE", "CPI", "FOMC", "LTV"}

# A sentence start: beginning of text, after terminal punctuation + space, or
# after a line break — optionally followed by opening quotes/inverted marks.
_SENTENCE_START = re.compile(r'(^|[.!?]\s+|\n\s*)([¿¡"\'(\[]*)([^\W\d_])')


def _unshout(text):
    words = []
    for i, w in enumerate(text.split()):
        if w.strip(".,!?:;¿¡") in ACRONYMS:
            words.append(w)
        elif i == 0:
            words.append(w.capitalize())
        else:
            words.append(w.lower())
    return " ".join(words)


def fix_case(text):
    """ALL CAPS -> sentence case (acronyms kept); all-lowercase -> every
    sentence capitalised; otherwise only guarantee a capital first letter."""
    text = (text or "").strip()
    if not text:
        return text
    if text.isupper():
        return _unshout(text)
    if not any(ch.isupper() for ch in text):
        return _SENTENCE_START.sub(
            lambda m: m.group(1) + m.group(2) + m.group(3).upper(), text)
    m = re.search(r"[^\W\d_]", text)
    if m and text[m.start()].islower():
        text = text[:m.start()] + text[m.start()].upper() + text[m.start() + 1:]
    return text


# Every free-text field of a carousel that reaches a slide, a caption or an email.
TEXT_FIELDS = ("title", "cover_text", "hook", "what_happened_heading", "what_happened",
               "my_take_heading", "my_take", "action_lo", "action_realtor",
               "cta_question", "caption")


def fix_carousel(c):
    """Normalise capitalisation in place on a Carousel model or a plain dict."""
    is_dict = isinstance(c, dict)
    for f in TEXT_FIELDS:
        v = c.get(f) if is_dict else getattr(c, f, None)
        if isinstance(v, str):
            fixed = fix_case(v)
            if is_dict:
                c[f] = fixed
            else:
                setattr(c, f, fixed)
    breakdown = c.get("breakdown") if is_dict else getattr(c, "breakdown", None)
    for b in breakdown or []:
        for f in ("heading", "body"):
            v = b.get(f) if isinstance(b, dict) else getattr(b, f, None)
            if isinstance(v, str):
                if isinstance(b, dict):
                    b[f] = fix_case(v)
                else:
                    setattr(b, f, fix_case(v))
    return c
