"""
Render 3 self-contained Instagram carousel HTML previews for SafeTrust Mortgage
from carousel_content.json (produced by write_carousels.py). Each carousel is a
420px-wide IG frame with 7 swipeable 4:5 slides. Run:  python generate_carousels.py
Then open the produced carousels/*.html files in a browser to swipe through them.
"""
import base64
import html
import io
import json
from datetime import datetime
from pathlib import Path

# Run date, e.g. "13th July 2024" (Eastern — matches the daily 6am ET run).
try:
    from zoneinfo import ZoneInfo
    _TODAY = datetime.now(ZoneInfo("America/New_York"))
except Exception:
    _TODAY = datetime.now()


def _ordinal_suffix(n):
    # Handles st/nd/rd/th, including the 11th/12th/13th exceptions.
    return "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")


# e.g. July 13<sup>th</sup> 2026 — the ordinal suffix is superscripted.
DATE_HTML = (f'{_TODAY.strftime("%B")} {_TODAY.day}'
             f'<sup style="font-size:0.6em;letter-spacing:0;">{_ordinal_suffix(_TODAY.day)}</sup>'
             f' {_TODAY.year}')

# Spanish date, e.g. "13 de julio de 2026" (Spanish months are lowercase).
_MONTHS_ES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
              "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
DATE_HTML_ES = f'{_TODAY.day} de {_MONTHS_ES[_TODAY.month - 1]} de {_TODAY.year}'

# ---------------------------------------------------------------- brand tokens
B           = "#1E3A5F"   # BRAND_PRIMARY  (navy)
LIGHT       = "#3B6AA0"   # BRAND_LIGHT
DARK        = "#142842"   # BRAND_DARK
LIGHT_BG    = "#F4F6F9"   # light slide base (cool off-white)
LIGHT_BORDER= "#E2E6EC"   # dividers on light slides
DARK_BG     = "#0F172A"   # dark slide base (navy-tinted near-black)
# Cinematic corner-glow gradients: a blue/teal light blooms from the bottom-left
# into near-black (dark) or off-white (light) — the "1 Billion Followers" look.
LIGHT_GRAD  = "radial-gradient(140% 130% at 10% 115%, #BFD7EF 0%, #D4E3F3 34%, #E9F0F8 66%, #F4F7FB 100%)"
DARK_GRAD   = "radial-gradient(140% 130% at 8% 116%, #2E88C8 0%, #1C6098 20%, #124067 42%, #0B2743 66%, #060D18 100%)"
GRAD        = "radial-gradient(140% 132% at 6% 116%, #3EA0DE 0%, #2379B6 20%, #17568A 42%, #103C64 66%, #0A2138 100%)"
MUTED       = "#5A6B7E"   # body text on light
SUBTLE      = "#8A94A0"   # descriptions on light
HANDLE      = "safetrust_mortgage"
HANDLE_ES   = "quierounacasa_com"   # IG handle shown on the Spanish carousels' CTA slide
NMLS_NUMBER = "2178036"
LOGO_BLUE   = "#1E56A4"   # sampled from the logo wordmark
LOGO_GRAY   = "#818285"   # sampled from the logo subtitle
MID_H       = 34          # Mortgage Intelligence Daily logo height (now trimmed tight to its text)
ST_H        = 30          # SafeTrust logo height
ASSETS      = Path(__file__).parent / "assets"

# ---------------------------------------------------------------- brand logo
def _process_raster(raw):
    """Trim white margins and knock out the white background so the logo sits
    cleanly on any slide. Returns (png_bytes, mime) or None if Pillow is absent."""
    try:
        from PIL import Image, ImageChops
    except Exception:
        return None
    im = Image.open(io.BytesIO(raw)).convert("RGBA")
    a = im.getchannel("A")
    if a.getextrema()[0] < 250:
        # Already has a transparent background — trim to the substantial artwork.
        # Threshold on alpha so faint anti-aliased padding doesn't inflate the crop.
        bbox = a.point(lambda v: 255 if v >= 40 else 0).getbbox()
        if bbox:
            im = im.crop(bbox)
    else:
        # Opaque image — treat light pixels (including a transparency checkerboard) as
        # background. Alpha ramps by darkness so a dark logo on a light/checkerboard
        # background comes out cleanly, with anti-aliased edges.
        lum = im.convert("L")
        alpha = lum.point(lambda v: 0 if v > 200 else 255 if v < 120 else int(255 * (200 - v) / 80))
        # Trim to real ink (alpha>=40), not faint halo pixels that would leave padding.
        bbox = alpha.point(lambda v: 255 if v >= 40 else 0).getbbox()
        if bbox:
            im = im.crop(bbox)
            alpha = alpha.crop(bbox)
        im.putalpha(alpha)
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue(), "image/png"


def _embed(path):
    raw = path.read_bytes()
    if path.suffix.lower() == ".svg":
        return "data:image/svg+xml;base64," + base64.b64encode(raw).decode()
    processed = _process_raster(raw)
    if processed:
        data, mime = processed
    else:
        data = raw
        mime = "image/jpeg" if path.suffix.lower() in (".jpg", ".jpeg") else "image/png"
    return f"data:{mime};base64," + base64.b64encode(data).decode()


def _find_logo(candidates):
    for name in candidates:
        p = ASSETS / name
        if p.exists():
            return _embed(p)
    return None

# Primary publication logo — "Mortgage Intelligence Daily" (the daily is a SafeTrust dept).
MID_URI = _find_logo(["Mortgage Intelligence Daily.png", "mortgage-intelligence-daily.png",
                      "mortgage_intelligence_daily.png", "mid.png"])
# SafeTrust Mortgage house logo — kept as-is, used as the "by …" attribution.
LOGO_URI = _find_logo(["logo.png", "logo.jpg", "logo.jpeg", "logo.svg"])
LOGO_WHITE_URI = _find_logo(["logo-white.png", "logo-white.svg", "logo_white.png"])
# Equal Housing Opportunity badge (white) — shown bottom-right on the final slide.
BADGE_URI = _find_logo(["equal-housing.png", "equal-housing.svg", "badge.png", "badge.svg"])
# QuieroUnaCasa.com logo — replaces the SafeTrust logo on the Spanish carousels.
# Taller than the SafeTrust wordmark (house art + stacked text), hence its own heights.
QUC_URI = _find_logo(["QUC.png", "quc.png", "quierounacasa.png"])
QUC_H      = 48   # masthead height on slide 1
QUC_HERO_H = 68   # hero height on the final CTA slide

# Per-language chrome labels (the model translates the copy; these are the fixed
# slide labels). Spanish is formal ("usted").
LABELS = {
    "en": {
        "what_happened": "What Happened", "breakdown": "The Breakdown",
        "my_take": "My Take", "angle": "The Angle", "what_to_do": "What To Do",
        "next_move": "Your next move", "for_lo": "For Loan Officers",
        "for_realtor": "For Realtors", "join": "Join The Conversation",
        "source": "Source",
    },
    "es": {
        "what_happened": "Qu&eacute; Pas&oacute;", "breakdown": "El Desglose",
        "my_take": "Mi Opini&oacute;n", "angle": "El &Aacute;ngulo",
        "what_to_do": "Qu&eacute; Hacer", "next_move": "Su pr&oacute;ximo paso",
        "for_lo": "Para Oficiales de Pr&eacute;stamo",
        "for_realtor": "Para Agentes de Bienes Ra&iacute;ces",
        "join": "&Uacute;nase a la Conversaci&oacute;n", "source": "Fuente",
    },
}
# Headshot for the "My Take" slide — embedded raw (it's a photo, so the logo
# white-knockout in _process_raster must not run on it).
_HEADSHOT = ASSETS / "marsel-headshot.jpg"
HEADSHOT_URI = ("data:image/jpeg;base64," + base64.b64encode(_HEADSHOT.read_bytes()).decode()
                if _HEADSHOT.exists() else None)
# Background-removed cutout of the same headshot — stands along the right edge of
# the "My Take" slide. _embed trims the transparent margins around the figure.
_CUTOUT = ASSETS / "marsel-cutout.png"
CUTOUT_URI = _embed(_CUTOUT) if _CUTOUT.exists() else None

# ---------------------------------------------------------------- components
def tag(text, bg):
    color = B if bg == "light" else (LIGHT if bg == "dark" else "rgba(255,255,255,0.65)")
    return (f'<span class="sans" style="display:inline-block;font-size:10px;font-weight:600;'
            f'letter-spacing:2px;color:{color};margin-bottom:16px;text-transform:uppercase;">{text}</span>')

def _nmls_line(on_light):
    label = LOGO_GRAY if on_light else "rgba(255,255,255,0.6)"
    num = LOGO_BLUE if on_light else "#fff"
    return (f'<p class="sans" style="font-size:11px;font-weight:600;letter-spacing:2px;'
            f'margin-top:8px;"><span style="color:{label};">NMLS</span> '
            f'<span style="color:{num};">{NMLS_NUMBER}</span></p>')


def logo_lockup(on_light, show_mid=True, es=False):
    """Masthead: the brand logo (+ NMLS) and the larger Mortgage Intelligence
    Daily logo (+ run date) side by side, split by a thin divider. The brand is
    SafeTrust Mortgage, or QuieroUnaCasa.com on the Spanish carousels. When
    show_mid=False (the final CTA slide) only the brand logo is shown."""
    # --- brand logo + NMLS ---
    use_quc = es and QUC_URI
    brand_uri   = QUC_URI if use_quc else LOGO_URI
    brand_white = None if use_quc else LOGO_WHITE_URI  # QUC has no white variant
    brand_alt   = "QuieroUnaCasa.com" if use_quc else "SafeTrust Mortgage"
    brand_h     = QUC_H if use_quc else ST_H
    hero_h      = QUC_HERO_H if use_quc else 42
    if brand_uri:
        if on_light:
            st_src, st_filt = brand_uri, ""
        elif brand_white:
            st_src, st_filt = brand_white, ""
        else:
            st_src, st_filt = brand_uri, "filter:brightness(0) invert(1);"
        brand = (f'<img src="{st_src}" alt="{brand_alt}" '
                 f'style="height:{brand_h}px;width:auto;max-width:150px;display:block;margin:0 auto;{st_filt}">')
    else:
        stcolor = DARK if on_light else "#fff"
        brand = (f'<div class="sans" style="font-size:14px;font-weight:600;letter-spacing:0.5px;'
                 f'color:{stcolor};">{brand_alt}</div>')
    left = f'<div style="text-align:center;">{brand}{_nmls_line(on_light)}</div>'

    # Brand logo only, at hero size, left-justified, with the NMLS line
    # centered under the logo (shrink-wrapped block stays left).
    if not show_mid:
        if brand_uri:
            hero_st = (f'<img src="{st_src}" alt="{brand_alt}" '
                       f'style="height:{hero_h}px;width:auto;max-width:230px;display:block;margin:0 auto;{st_filt}">')
        else:
            hero_st = brand
        return (f'<div style="margin-bottom:24px;width:100%;text-align:left;">'
                f'<div style="display:inline-block;text-align:center;">'
                f'{hero_st}{_nmls_line(on_light)}</div></div>')

    # --- Mortgage Intelligence Daily logo + date ---
    if MID_URI:
        mid_filt = "" if on_light else "filter:brightness(0) invert(1);"
        mid = (f'<img src="{MID_URI}" alt="Mortgage Intelligence Daily" '
               f'style="height:{MID_H}px;width:auto;max-width:240px;display:block;margin:0 auto;{mid_filt}">')
    else:
        midcolor = DARK if on_light else "#fff"
        mid = (f'<div class="serif" style="font-size:15px;font-weight:700;color:{midcolor};'
               f'line-height:1.1;">Mortgage<br>Intelligence Daily</div>')
    date_color = "#000" if on_light else "rgba(255,255,255,0.7)"
    # Date sits just below the MID logo text (the PNG is trimmed tight to the text).
    # Spanish carousels flag the edition between the logo and the date.
    edition = ""
    if es:
        edition = (f'<p class="sans" style="font-size:10px;font-weight:600;color:{date_color};'
                   f'letter-spacing:2px;margin-top:5px;">- En Espa&ntilde;ol -</p>')
    date_html = (f'<p class="sans" style="font-size:11px;font-weight:500;color:{date_color};'
                 f'letter-spacing:1px;margin-top:{3 if es else 5}px;">{DATE_HTML_ES if es else DATE_HTML}</p>')
    right = f'<div style="text-align:center;">{mid}{edition}{date_html}</div>'

    divcolor = "rgba(0,0,0,0.22)" if on_light else "rgba(255,255,255,0.35)"
    divider = f'<div style="width:1px;height:46px;background:{divcolor};align-self:center;flex-shrink:0;"></div>'
    return (f'<div style="margin-bottom:22px;width:100%;transform:translateY(-18px);">'
            f'<div style="display:flex;align-items:center;justify-content:center;gap:16px;">'
            f'{left}{divider}{right}</div></div>')

def h_light(text, size=29):
    return (f'<h2 class="serif" style="font-size:{size}px;font-weight:700;color:{DARK};'
            f'line-height:1.13;letter-spacing:-0.5px;margin-bottom:14px;">{text}</h2>')

def h_dark(text, size=29):
    return (f'<h2 class="serif" style="font-size:{size}px;font-weight:700;color:#fff;'
            f'line-height:1.13;letter-spacing:-0.5px;margin-bottom:14px;">{text}</h2>')

def p_light(text):
    return (f'<p class="sans" style="font-size:14px;color:{MUTED};line-height:1.55;'
            f'margin-bottom:18px;">{text}</p>')

def p_dark(text):
    return (f'<p class="sans" style="font-size:14px;color:rgba(255,255,255,0.72);'
            f'line-height:1.55;margin-bottom:18px;">{text}</p>')

def minilabel_dark(text):
    return (f'<p class="sans" style="font-size:11px;color:rgba(255,255,255,0.45);'
            f'letter-spacing:1px;text-transform:uppercase;margin-bottom:10px;">{text}</p>')

def pill(text):
    return (f'<span class="sans" style="font-size:11px;padding:6px 13px;'
            f'background:rgba(255,255,255,0.07);border-radius:20px;color:{LIGHT};'
            f'display:inline-block;">{text}</span>')

def strike_pill(text):
    return (f'<span class="sans" style="font-size:11px;padding:6px 13px;'
            f'border:1px solid rgba(255,255,255,0.14);border-radius:20px;color:#8A9BB5;'
            f'text-decoration:line-through;display:inline-block;">{text}</span>')

def pills_row(items, strike=False):
    inner = "".join((strike_pill(t) if strike else pill(t)) for t in items)
    return f'<div style="display:flex;flex-wrap:wrap;gap:8px;margin-top:4px;">{inner}</div>'

def _fit_quote_size(text):
    """Quote font size stepped down by text length so long quotes (Spanish runs
    ~25% longer than English) never overflow the My Take slide."""
    n = len(text)
    if n <= 180:
        return 16
    if n <= 240:
        return 14
    if n <= 300:
        return 12.5
    return 11.5


def quote_box(label, quote, qsize=16):
    lh = 1.45 if qsize >= 14 else 1.4
    return (f'<div style="padding:16px 18px;background:rgba(255,255,255,0.07);border-radius:12px;'
            f'border:1px solid rgba(255,255,255,0.14);margin-top:6px;">'
            f'<p class="sans" style="font-size:11px;color:rgba(255,255,255,0.55);margin-bottom:8px;'
            f'letter-spacing:1px;text-transform:uppercase;">{label}</p>'
            f'<p class="serif" style="font-size:{qsize}px;color:#fff;font-style:italic;'
            f'line-height:{lh};">&ldquo;{quote}&rdquo;</p></div>')

def feature_row(label, desc, last=False):
    border = "" if last else f"border-bottom:1px solid {LIGHT_BORDER};"
    return (f'<div style="display:flex;align-items:flex-start;gap:14px;padding:11px 0;{border}">'
            f'<span style="color:{B};font-size:15px;width:18px;text-align:center;flex-shrink:0;'
            f'line-height:1.4;">&#10003;</span>'
            f'<div style="display:flex;flex-direction:column;gap:2px;">'
            f'<span class="sans" style="font-size:14px;font-weight:600;color:{DARK};line-height:1.25;">{label}</span>'
            f'<span class="sans" style="font-size:12px;color:{SUBTLE};line-height:1.4;">{desc}</span></div></div>')

def step_row(num, title, desc, last=False):
    border = "" if last else f"border-bottom:1px solid {LIGHT_BORDER};"
    return (f'<div style="display:flex;align-items:flex-start;gap:16px;padding:12px 0;{border}">'
            f'<span class="serif" style="font-size:26px;font-weight:300;color:{B};min-width:34px;'
            f'line-height:1;">{num}</span>'
            f'<div style="display:flex;flex-direction:column;gap:2px;">'
            f'<span class="sans" style="font-size:14px;font-weight:600;color:{DARK};line-height:1.25;">{title}</span>'
            f'<span class="sans" style="font-size:12px;color:{SUBTLE};line-height:1.4;">{desc}</span></div></div>')

def stack(rows):
    return f'<div style="margin-top:2px;">{"".join(rows)}</div>'

def cta_button(text):
    return (f'<div style="display:inline-flex;align-items:center;gap:8px;padding:13px 30px;'
            f'background:{LIGHT_BG};color:{DARK};font-family:\'Work Sans\',sans-serif;'
            f'font-weight:600;font-size:14px;border-radius:28px;margin-top:6px;">{text}</div>')

def handle_line(on_light=False, handle=HANDLE):
    color = SUBTLE if on_light else "rgba(255,255,255,0.6)"
    return (f'<p class="sans" style="font-size:12px;color:{color};margin-top:16px;'
            f'letter-spacing:0.5px;">@{handle}</p>')

def big_stat(text):
    return (f'<div class="serif" style="font-size:78px;font-weight:700;color:{B};line-height:1;'
            f'letter-spacing:-2px;margin-bottom:8px;">{text}</div>')

# ---------------------------------------------------------------- slide + frame
def progress_bar(index, total, is_light):
    pct = ((index + 1) / total) * 100
    track = "rgba(0,0,0,0.08)" if is_light else "rgba(255,255,255,0.12)"
    fill  = B if is_light else "#fff"
    label = "rgba(0,0,0,0.3)" if is_light else "rgba(255,255,255,0.4)"
    return (f'<div style="position:absolute;bottom:0;left:0;right:0;padding:16px 28px 20px;'
            f'z-index:10;display:flex;align-items:center;gap:10px;">'
            f'<div style="flex:1;height:3px;background:{track};border-radius:2px;overflow:hidden;">'
            f'<div style="height:100%;width:{pct:.4f}%;background:{fill};border-radius:2px;"></div></div>'
            f'<span style="font-size:11px;color:{label};font-weight:500;">{index + 1}/{total}</span></div>')

def swipe_arrow(is_light):
    bg = "rgba(0,0,0,0.06)" if is_light else "rgba(255,255,255,0.08)"
    stroke = "rgba(0,0,0,0.25)" if is_light else "rgba(255,255,255,0.35)"
    return (f'<div style="position:absolute;right:0;top:0;bottom:0;width:48px;z-index:9;'
            f'display:flex;align-items:center;justify-content:center;'
            f'background:linear-gradient(to right,transparent,{bg});">'
            f'<svg width="24" height="24" viewBox="0 0 24 24" fill="none">'
            f'<path d="M9 6l6 6-6 6" stroke="{stroke}" stroke-width="2.5" '
            f'stroke-linecap="round" stroke-linejoin="round"/></svg></div>')

def eho_badge(is_light):
    """Equal Housing Lender badge, bottom-right above the progress bar."""
    if not BADGE_URI:
        return ""
    # Badge art is dark after background removal: darken on light slides, invert to white on dark.
    filt = "filter:brightness(0);" if is_light else "filter:brightness(0) invert(1);"
    return (f'<img src="{BADGE_URI}" alt="Equal Housing Lender" '
            f'style="position:absolute;right:30px;bottom:56px;width:48px;height:auto;'
            f'z-index:8;opacity:0.9;{filt}">')


def source_line(source, on_light=False, label="Source"):
    """"Source: <outlet>" shown under the @handle on the final slide."""
    source = (source or "").strip()
    if not source:
        return ""
    color = SUBTLE if on_light else "rgba(255,255,255,0.5)"
    return (f'<p class="sans" style="font-size:11px;color:{color};margin-top:6px;'
            f'letter-spacing:0.3px;">{label}: {html.escape(source)}</p>')

def ghost_number(num, bg):
    """Oversized, very faint index numeral filling the upper area of a slide as a
    background accent — anchors sparse text slides so the top doesn't read empty."""
    if bg == "light":
        color = "rgba(20,40,66,0.055)"
    elif bg == "gradient":
        color = "rgba(255,255,255,0.09)"
    else:
        color = "rgba(255,255,255,0.055)"
    return (f'<div class="serif" style="position:absolute;top:2px;left:26px;z-index:1;'
            f'font-size:210px;font-weight:700;line-height:1;letter-spacing:-8px;'
            f'color:{color};pointer-events:none;user-select:none;">{num}</div>')

def render_slide(slide, index, total):
    bg = slide["bg"]
    is_light = bg == "light"
    if bg == "light":
        bgcss = f"background:{LIGHT_GRAD};"
    elif bg == "dark":
        bgcss = f"background:{DARK_GRAD};"
    else:
        bgcss = f"background:{GRAD};"
    last = index == total - 1
    arrow = "" if last else swipe_arrow(is_light)
    badge = eho_badge(is_light) if last else ""
    ghost = ghost_number(f"{index + 1:02d}", bg) if slide.get("ghost") else ""
    justify = slide.get("justify", "flex-end")
    underlay = slide.get("underlay", "")
    return (f'<div class="slide" style="{bgcss}">{underlay}{arrow}{badge}{ghost}'
            f'<div class="slide-content" style="justify-content:{justify};">{slide["content"]}</div>'
            f'{progress_bar(index, total, is_light)}</div>')

ICONS_SVG = (
    '<svg viewBox="0 0 24 24" fill="none" stroke="#262626" stroke-width="1.8"><path d="M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.6l-1-1a5.5 5.5 0 1 0-7.8 7.8l1 1L12 21l7.8-7.6 1-1a5.5 5.5 0 0 0 0-7.8z"/></svg>'
    '<svg viewBox="0 0 24 24" fill="none" stroke="#262626" stroke-width="1.8"><path d="M21 11.5a8.4 8.4 0 0 1-8.5 8.5 8.4 8.4 0 0 1-4-1L3 20l1-5.5a8.4 8.4 0 0 1-1-4A8.4 8.4 0 0 1 11.5 2 8.4 8.4 0 0 1 21 11.5z"/></svg>'
    '<svg viewBox="0 0 24 24" fill="none" stroke="#262626" stroke-width="1.8"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>'
)
BOOKMARK_SVG = '<svg viewBox="0 0 24 24" fill="none" stroke="#262626" stroke-width="1.8" style="margin-left:auto;"><path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z"/></svg>'

def build_html(title, caption_desc, slides):
    total = len(slides)
    slides_html = "".join(render_slide(s, i, total) for i, s in enumerate(slides))
    dots_html = "".join('<div class="ig-dot"></div>' for _ in range(total))
    head = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=Libre+Baskerville:ital,wght@0,400;0,700;1,400&family=Work+Sans:wght@400;500;600;700&display=swap');
*{margin:0;padding:0;box-sizing:border-box;}
body{background:#E9ECF1;display:flex;align-items:center;justify-content:center;min-height:100vh;padding:24px;font-family:'Work Sans',sans-serif;}
.serif{font-family:'Libre Baskerville',serif;}
.sans{font-family:'Work Sans',sans-serif;}
.ig-frame{width:420px;background:#fff;border-radius:16px;box-shadow:0 12px 40px rgba(0,0,0,0.16);overflow:hidden;}
.ig-header{display:flex;align-items:center;gap:10px;padding:11px 14px;border-bottom:1px solid #efefef;}
.ig-avatar{width:34px;height:34px;border-radius:50%;background:#1E3A5F;display:flex;align-items:center;justify-content:center;color:#fff;font-weight:700;font-family:'Libre Baskerville',serif;font-size:15px;flex-shrink:0;}
.ig-handle{font-size:13px;font-weight:600;color:#111;}
.ig-sub{font-size:11px;color:#8e8e8e;}
.carousel-viewport{width:420px;height:525px;overflow:hidden;position:relative;cursor:grab;touch-action:pan-y;}
.carousel-track{display:flex;height:100%;transition:transform 0.35s cubic-bezier(0.22,1,0.36,1);will-change:transform;}
.slide{width:420px;height:525px;position:relative;flex-shrink:0;display:flex;flex-direction:column;overflow:hidden;}
.slide-content{flex:1;display:flex;flex-direction:column;padding:0 36px 52px;position:relative;z-index:2;}
.ig-dots{display:flex;gap:5px;justify-content:center;padding:12px 0 6px;}
.ig-dot{width:6px;height:6px;border-radius:50%;background:#d3d6db;transition:background .2s;}
.ig-dot.active{background:#1E3A5F;}
.ig-actions{display:flex;align-items:center;gap:15px;padding:6px 14px 2px;}
.ig-actions svg{width:24px;height:24px;}
.ig-caption{padding:6px 14px 16px;font-size:13px;color:#111;line-height:1.45;white-space:pre-line;}
.ig-caption .h{font-weight:600;}
.ig-time{font-size:10px;color:#8e8e8e;letter-spacing:.5px;margin-top:8px;text-transform:uppercase;}
</style></head><body>""".replace("__TITLE__", html.escape(title))

    frame = f"""<div class="ig-frame">
  <div class="ig-header">
    <div class="ig-avatar">S</div>
    <div><div class="ig-handle">{HANDLE}</div><div class="ig-sub">SafeTrust Mortgage</div></div>
  </div>
  <div class="carousel-viewport"><div class="carousel-track">{slides_html}</div></div>
  <div class="ig-dots">{dots_html}</div>
  <div class="ig-actions">{ICONS_SVG}{BOOKMARK_SVG}</div>
  <div class="ig-caption"><span class="h">{HANDLE}</span> {caption_desc}
    <div class="ig-time">2 hours ago</div>
  </div>
</div>"""

    script = f"""<script>
const vp=document.querySelector('.carousel-viewport');
const track=document.querySelector('.carousel-track');
const dots=[...document.querySelectorAll('.ig-dot')];
let idx=0,total={total},startX=0,dragging=false,curX=0;
function go(i){{idx=Math.max(0,Math.min(total-1,i));track.style.transition='transform 0.35s cubic-bezier(0.22,1,0.36,1)';track.style.transform='translateX('+(-idx*420)+'px)';dots.forEach((d,j)=>d.classList.toggle('active',j===idx));}}
vp.addEventListener('pointerdown',e=>{{dragging=true;startX=e.clientX;curX=0;track.style.transition='none';vp.setPointerCapture(e.pointerId);vp.style.cursor='grabbing';}});
vp.addEventListener('pointermove',e=>{{if(!dragging)return;curX=e.clientX-startX;track.style.transform='translateX('+(-idx*420+curX)+'px)';}});
function end(){{if(!dragging)return;dragging=false;vp.style.cursor='grab';if(curX<-45&&idx<total-1)go(idx+1);else if(curX>45&&idx>0)go(idx-1);else go(idx);}}
vp.addEventListener('pointerup',end);vp.addEventListener('pointercancel',end);
document.addEventListener('keydown',e=>{{if(e.key==='ArrowRight')go(idx+1);if(e.key==='ArrowLeft')go(idx-1);}});
go(0);
</script></body></html>"""
    return head + frame + script

# ---------------------------------------------------------------- data -> slides
def render_carousel_slides(c, cover_blue=False, lang="en"):
    """Build the ~9-slide industry-analysis script from a structured carousel dict
    (see write_carousels.py): Hook, What Happened, 4x Breakdown, My Take, What To
    Do, CTA. cover_blue flips slide 1 from a white cover to a blue-gradient one.
    lang="es" renders the fixed chrome (labels, date, brand logo) in Spanish."""
    e = html.escape
    L = LABELS[lang]
    es = lang == "es"

    # 1 — Hook / cover (centered) — brand + MID paired masthead.
    if cover_blue:
        hook = (logo_lockup(False, es=es) + tag(e(c["hook_tag"]), "gradient")
                + h_dark(e(c["cover_text"]), 33) + p_dark(e(c["hook"])))
        slides = [{"bg": "gradient", "justify": "center", "content": hook}]
    else:
        hook = (logo_lockup(True, es=es) + tag(e(c["hook_tag"]), "light")
                + h_light(e(c["cover_text"]), 33) + p_light(e(c["hook"])))
        slides = [{"bg": "light", "justify": "center", "content": hook}]

    # 2 — What happened (dark)
    wh = (tag(L["what_happened"], "dark") + h_dark(e(c["what_happened_heading"]))
          + p_dark(e(c["what_happened"])))
    slides.append({"bg": "dark", "content": wh, "ghost": True})

    # 3-6 — The breakdown (one idea per slide, alternating backgrounds)
    bgs = ["light", "gradient", "dark", "light"]
    for i, b in enumerate(c["breakdown"]):
        bg = bgs[i % len(bgs)]
        head = h_light if bg == "light" else h_dark
        body = p_light if bg == "light" else p_dark
        content = (tag(L["breakdown"], bg)
                   + head(e(b["heading"])) + body(e(b["body"])))
        slides.append({"bg": bg, "content": content, "ghost": True})

    # 7 — My take (gradient, centered) — the contrarian, screenshot slide.
    # The background-removed cutout stands along the right edge; the copy keeps
    # to a narrower left column so the figure stays clear of the text.
    mt = (tag(L["my_take"], "gradient")
          + h_dark(e(c["my_take_heading"]), 21 if es else 25)
          + quote_box(L["angle"], e(c["my_take"]), qsize=_fit_quote_size(c["my_take"])))
    slide7 = {"bg": "gradient", "justify": "center", "content": mt}
    if CUTOUT_URI:
        slide7["underlay"] = (
            f'<img src="{CUTOUT_URI}" alt="" style="position:absolute;right:-24px;'
            f'bottom:0;height:240px;width:auto;'
            f'filter:drop-shadow(0 12px 28px rgba(0,0,0,0.4));">')
        slide7["content"] = f'<div style="width:64%;">{mt}</div>'
    slides.append(slide7)

    # 8 — What to do (light) — one move for LOs, one for realtors
    wtd = tag(L["what_to_do"], "light") + h_light(L["next_move"])
    wtd += stack([
        feature_row(L["for_lo"], e(c["action_lo"]), last=False),
        feature_row(L["for_realtor"], e(c["action_realtor"]), last=True),
    ])
    slides.append({"bg": "light", "content": wtd, "ghost": True})

    # 9 — CTA (gradient, centered) — brand-only masthead, handle, source, EHO badge
    cta = (logo_lockup(False, show_mid=False, es=es) + tag(L["join"], "gradient")
           + h_dark(e(c["cta_question"]), 27) + handle_line(handle=HANDLE_ES if es else HANDLE)
           + source_line(c.get("source", ""), label=L["source"]))
    slides.append({"bg": "gradient", "justify": "center", "content": cta,
                   "source": c.get("source", "")})

    return slides

# ---------------------------------------------------------------- output
def main():
    base = Path(__file__).parent
    content_path = base / "carousel_content.json"
    if not content_path.exists():
        raise SystemExit(
            "carousel_content.json not found. Run `python write_carousels.py` first "
            "(it turns daily_news.json into slide copy via Claude)."
        )
    data = json.loads(content_path.read_text(encoding="utf-8"))
    carousels = data["carousels"][:3]
    carousels_es = data.get("carousels_es", [])[:3]

    # Cover colours alternate by day: one day 2 white + 1 blue, the next 2 blue +
    # 1 white, repeating. The run date drives it (and rotates which cover is blue).
    # Each Spanish carousel mirrors its English counterpart's cover colour.
    n = len(carousels)
    d = _TODAY.toordinal()
    blue_count = min(2 if d % 2 == 0 else 1, n)  # even day -> 2 blue, odd day -> 1 blue
    start = d % n if n else 0
    blue_covers = {(start + k) % n for k in range(blue_count)}
    print(f"Cover colours today: {blue_count} blue / {n - blue_count} white "
          f"(blue = carousels {sorted(i + 1 for i in blue_covers)})")

    # Carousels 1-3: English. Carousels 4-6: the Spanish translations (QUC brand).
    renders = [(c, "en", i in blue_covers) for i, c in enumerate(carousels)]
    renders += [(c, "es", i in blue_covers) for i, c in enumerate(carousels_es)]

    out_dir = base / "carousels"
    out_dir.mkdir(exist_ok=True)
    # Drop stale renders from a previous (possibly larger) set so exports and
    # emails never pick up yesterday's carousels beyond today's count.
    for old in out_dir.glob("carousel_*.html"):
        old.unlink()
    index_links = []
    for i, (c, lang, blue) in enumerate(renders):
        slides = render_carousel_slides(c, cover_blue=blue, lang=lang)
        doc = build_html(c.get("title", f"Carousel {i + 1}"), html.escape(c.get("caption", "")), slides)
        filename = f"carousel_{i + 1}.html"
        (out_dir / filename).write_text(doc, encoding="utf-8")
        label = f'{c.get("title", filename)} [{lang.upper()}]'
        index_links.append(f'<li><a href="{filename}">{html.escape(label)}</a> &mdash; {len(slides)} slides</li>')
        print(f"Wrote carousels/{filename}  ({len(slides)} slides) [{lang}] — {c.get('title', '')}")

    index = ("<!doctype html><meta charset='utf-8'><title>SafeTrust Carousels</title>"
             "<body style=\"font-family:sans-serif;max-width:640px;margin:60px auto;padding:0 20px;color:#142842;\">"
             "<h1 style='font-family:Georgia,serif;'>SafeTrust Mortgage &mdash; Carousel Previews</h1>"
             f"<ul style='line-height:2.2;font-size:17px;'>{''.join(index_links)}</ul></body>")
    (out_dir / "index.html").write_text(index, encoding="utf-8")
    print("Wrote carousels/index.html")

if __name__ == "__main__":
    main()
