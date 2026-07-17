"""
Render post_content.json (from write_post.py) into a 3-slide Instagram carousel
post — "Kickoff News" — one article per slide, styled like the "1 Billion Followers
Summit" reference: full-bleed photo background (from ./Marsel Images), dark + blue
corner-glow overlay, logo top-left, source pill top-right, headline + subhead
bottom-left, and a green "Swipe" button. Last slide shows the SafeTrust + Equal
Housing branding instead of the swipe button.

Run:  python generate_post.py   ->   post.html   (export_post.py -> PNGs)
"""
import base64
import html
import io
import json
from pathlib import Path

import generate_carousels as gc  # logos, badge, run date

BASE = Path(__file__).parent
CONTENT = BASE / "post_content.json"
OUT = BASE / "post.html"
IMG_DIR = BASE / "Marsel Images"

NAVY = "#1E3A5F"
GREEN = "#25D07A"


def _embed_bg(path):
    """Crop off the bottom watermark, downscale, and base64-embed a background photo."""
    from PIL import Image
    im = Image.open(path).convert("RGB")
    w, h = im.size
    im = im.crop((0, 0, w, int(h * 0.92)))          # drop bottom ~8% (Remini watermark)
    tw = 1080
    im = im.resize((tw, round(im.height * tw / im.width)))
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=84)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def _bg_images(n):
    imgs = sorted(p for p in IMG_DIR.glob("*") if p.suffix.lower() in (".jpg", ".jpeg", ".png"))
    if not imgs:
        return [None] * n
    doy = gc._TODAY.timetuple().tm_yday           # rotate the chosen photos daily
    return [_embed_bg(imgs[(doy + i) % len(imgs)]) for i in range(n)]


def _logo_lockup():
    return (f'<div style="position:absolute;top:24px;left:26px;display:flex;align-items:center;gap:9px;z-index:4;">'
            f'<div style="width:34px;height:34px;border-radius:9px;background:#fff;display:flex;align-items:center;justify-content:center;">'
            f'<span class="sans" style="font-weight:800;font-size:15px;color:{NAVY};letter-spacing:-0.5px;">KN</span></div>'
            f'<div class="sans" style="color:#fff;font-size:10px;font-weight:700;letter-spacing:1.5px;line-height:1.15;">KICKOFF<br>NEWS</div></div>')


def _brand_lockup():
    st = (f'<img src="{gc.LOGO_URI}" alt="SafeTrust Mortgage" style="height:20px;filter:brightness(0) invert(1);">'
          if gc.LOGO_URI else '<span class="sans" style="color:#fff;font-weight:600;">SafeTrust Mortgage</span>')
    badge = (f'<img src="{gc.BADGE_URI}" alt="Equal Housing Lender" style="height:30px;filter:brightness(0) invert(1);opacity:0.9;">'
             if gc.BADGE_URI else '')
    return (f'<div style="display:flex;align-items:center;gap:12px;margin-top:16px;">'
            f'{st}<span class="sans" style="color:rgba(255,255,255,0.65);font-size:9px;font-weight:600;letter-spacing:1px;">NMLS {gc.NMLS_NUMBER}</span>{badge}</div>')


def render_slide(item, bg, last):
    e = html.escape
    headline = e(item.get("headline", "").strip())
    line = e(item.get("line", "").strip())
    source = e(item.get("source", "").strip())
    img = (f'<img src="{bg}" alt="" style="position:absolute;inset:0;width:100%;height:100%;'
           f'object-fit:cover;object-position:center 20%;">') if bg else ''
    overlay = ('<div style="position:absolute;inset:0;background:'
               'radial-gradient(135% 82% at 3% 115%, rgba(46,116,180,0.55) 0%, rgba(46,116,180,0) 46%),'
               'linear-gradient(180deg, rgba(4,9,17,0.72) 0%, rgba(4,9,17,0.16) 20%, rgba(4,9,17,0.05) 40%, '
               'rgba(5,11,22,0.60) 65%, rgba(4,9,18,0.95) 100%);"></div>')
    pill = (f'<div style="position:absolute;top:26px;right:26px;z-index:4;">'
            f'<span class="sans" style="background:#fff;color:#15243a;font-size:10px;font-weight:700;'
            f'padding:6px 13px;border-radius:20px;white-space:nowrap;">{source}</span></div>') if source else ''
    cta = _brand_lockup() if last else (
        f'<div style="margin-top:16px;"><span class="sans" style="display:inline-flex;align-items:center;gap:7px;'
        f'background:{GREEN};color:#06351f;font-size:12px;font-weight:700;padding:9px 18px;border-radius:22px;">Swipe &rarr;</span></div>')
    return (f'<div class="slide">{img}{overlay}{_logo_lockup()}{pill}'
            f'<div style="position:absolute;left:30px;right:30px;bottom:32px;z-index:4;">'
            f'<h1 class="sans" style="color:#fff;font-size:30px;font-weight:800;line-height:1.08;letter-spacing:-0.6px;margin:0;">{headline}</h1>'
            f'<p class="sans" style="color:rgba(255,255,255,0.9);font-size:14px;line-height:1.5;font-weight:500;margin:11px 0 0;">{line}</p>'
            f'{cta}</div></div>')


def build_html(data):
    items = data.get("items", [])[:3]
    n = len(items)
    bgs = _bg_images(n)
    slides = "".join(render_slide(it, bgs[i], last=(i == n - 1)) for i, it in enumerate(items))
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Kickoff News &mdash; {gc.DATE_HTML}</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=Work+Sans:wght@400;500;600;700;800&display=swap');
*{{margin:0;padding:0;box-sizing:border-box;}}
body{{margin:0;font-family:'Work Sans',sans-serif;background:#0a1018;}}
.sans{{font-family:'Work Sans',sans-serif;}}
.slide{{width:420px;height:525px;position:relative;overflow:hidden;background:#0a1018;}}
</style></head>
<body>{slides}</body></html>"""


def main():
    if not CONTENT.exists():
        raise SystemExit("post_content.json not found. Run `python write_post.py` first.")
    data = json.loads(CONTENT.read_text(encoding="utf-8"))
    OUT.write_text(build_html(data), encoding="utf-8")
    print(f"Wrote {OUT.name} — {min(len(data.get('items', [])), 3)} slides")


if __name__ == "__main__":
    main()
