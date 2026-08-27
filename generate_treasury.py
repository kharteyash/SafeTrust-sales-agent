"""
Render the daily 10-Year Treasury market card: one 1080x1350 PNG in the exact
carousel theme (navy gradient, same masthead, serif/sans pairing) showing the
live 10Y yield, an up/down trend arrow vs the previous close, and the last
7 trading days as a line chart.

Data: live quote from CNBC (quote.cnbc.com, the feed behind cnbc.com/quotes/US10Y,
real-time even overnight) and daily history from Yahoo Finance (^TNX, includes the
current day's intraday bar). FRED (DGS10) is the fallback for both — it lags a
business day or two but is a rock-solid government feed, so the 6am run can't die
on a quote outage.

Run after export_slides.py (Playwright must be installed):
    python generate_treasury.py
Output: carousels/treasury.html and carousels/slides/treasury.png
"""
import datetime
import json
import sys
import urllib.request
from pathlib import Path

# Reuse the carousel design system: brand tokens, masthead, fonts, gradients.
import generate_carousels as gc

BASE = Path(__file__).parent
DAYS = 7
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

CNBC_URL = ("https://quote.cnbc.com/quote-html-webservice/restQuote/symbolType/symbol"
            "?symbols=US10Y&requestMethod=itv&noform=1&partnerId=2&fund=1&exthrs=1&output=json")
YAHOO_URL = "https://query1.finance.yahoo.com/v8/finance/chart/%5ETNX?range=1mo&interval=1d"
FRED_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS10"

# Two themes, matching the carousel covers. The card takes the day's MINORITY
# cover colour: on 2-blue/1-white days it renders white (and vice versa) so the
# posted set stays balanced. Trend colors are status colors (falling yields read
# as good news for a mortgage audience); the arrow glyph + text carry the
# message, never color alone.
THEMES = {
    "dark": {
        "on_light": False,
        "bg": None,                      # filled from gc.GRAD after import
        "tag_bg": "gradient",
        "hero": "#fff",
        "up": "#F08A8A", "down": "#5BD08D", "flat": "rgba(255,255,255,0.7)",
        "vs": "rgba(255,255,255,0.55)",
        "kicker": "rgba(255,255,255,0.45)",
        "footer": "rgba(255,255,255,0.4)",
        "line": "rgba(255,255,255,0.88)",
        "axis": "rgba(255,255,255,0.18)",
        "date_lab": "rgba(255,255,255,0.45)",
        "val_first": "rgba(255,255,255,0.65)",
        "val_last": "#fff",
        "fill_top": "rgba(120,200,255,0.28)",
        "dot": "#38E0F0", "halo": "rgba(56,224,240,0.25)",
    },
    "light": {
        "on_light": True,
        "bg": None,                      # filled from gc.LIGHT_GRAD after import
        "tag_bg": "light",
        "hero": None,                    # filled from gc.DARK
        "up": "#C74A4A", "down": "#248F5B", "flat": None,  # flat: gc.MUTED
        "vs": None,                      # gc.MUTED
        "kicker": None,                  # gc.SUBTLE
        "footer": None,                  # gc.SUBTLE
        "line": "rgba(20,40,66,0.85)",
        "axis": "rgba(20,40,66,0.15)",
        "date_lab": "rgba(20,40,66,0.45)",
        "val_first": "rgba(20,40,66,0.6)",
        "val_last": None,                # gc.DARK
        "fill_top": "rgba(59,106,160,0.22)",
        "dot": "#12AEC4", "halo": "rgba(18,174,196,0.22)",
    },
}
THEMES["dark"]["bg"] = gc.GRAD
THEMES["light"]["bg"] = gc.LIGHT_GRAD
THEMES["light"]["hero"] = gc.DARK
THEMES["light"]["flat"] = gc.MUTED
THEMES["light"]["vs"] = gc.MUTED
THEMES["light"]["kicker"] = gc.SUBTLE
THEMES["light"]["footer"] = gc.SUBTLE
THEMES["light"]["val_last"] = gc.DARK


def _get(url, timeout=30):
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout).read()


def fetch_cnbc():
    """Live US10Y quote. Returns (last, previous_close, as_of_text) or None."""
    try:
        q = json.loads(_get(CNBC_URL))["FormattedQuoteResult"]["FormattedQuote"][0]
        last = float(q["last"].rstrip("%"))
        prev = float(q["previous_day_closing"].rstrip("%"))
        as_of = "live"
        try:
            t = datetime.datetime.fromisoformat(q["last_time"])
            as_of = (f"{t.month}/{t.day}/{t.year} "
                     f"{t.strftime('%I:%M %p').lstrip('0')} ET")
        except Exception:  # noqa: BLE001 — timestamp is cosmetic
            pass
        return last, prev, as_of
    except Exception as exc:  # noqa: BLE001 — fall back to Yahoo/FRED
        print(f"CNBC quote failed ({str(exc)[:120]}) — falling back.")
        return None


def fetch_yahoo(days=DAYS):
    """Last `days` daily closes from Yahoo ^TNX (includes today's intraday bar).
    Returns [(iso_date, value)] or None."""
    try:
        res = json.loads(_get(YAHOO_URL))["chart"]["result"][0]
        closes = res["indicators"]["quote"][0]["close"]
        pairs = [(datetime.datetime.fromtimestamp(t).strftime("%Y-%m-%d"), round(c, 3))
                 for t, c in zip(res["timestamp"], closes) if c is not None]
        return pairs[-days:] if len(pairs) >= 2 else None
    except Exception as exc:  # noqa: BLE001 — fall back to FRED
        print(f"Yahoo history failed ({str(exc)[:120]}) — falling back to FRED.")
        return None


def fetch_fred(days=DAYS):
    """Last `days` daily closes from FRED DGS10 (keyless CSV, ~1-2 days behind)."""
    lines = _get(FRED_URL).decode("utf-8").strip().splitlines()
    series = []
    for line in lines[1:]:
        date, value = line.split(",")
        if value not in (".", ""):
            series.append((date, float(value)))
    return series[-days:]


def get_data():
    """Returns (series, last, prev, as_of, source_label)."""
    live = fetch_cnbc()
    series = fetch_yahoo()
    hist_src = "Yahoo Finance (^TNX)"
    if series is None:
        series = fetch_fred()
        hist_src = "FRED (DGS10)"
    if len(series) < 2:
        raise SystemExit("No usable 10Y treasury history — cannot build the card.")
    if live:
        last, prev, as_of = live
        # Keep the chart's newest point in sync with the live headline number.
        series[-1] = (series[-1][0], last)
        source = f"Live quote: CNBC (US10Y) &mdash; History: {hist_src}"
    else:
        last, prev = series[-1][1], series[-2][1]
        as_of = _short_date(series[-1][0]) + f"/{series[-1][0][:4]} close"
        source = f"Source: {hist_src}"
    return series, last, prev, as_of, source


def _short_date(iso):
    y, m, d = iso.split("-")
    return f"{int(m)}/{int(d)}"


def build_chart_svg(series, t, width=348, height=170):
    """Minimal single-series line chart: 2px line, faint area fill, cyan end dot
    (echoes the brand icon), first/last value labels, small date labels."""
    pad_l, pad_r, pad_t, pad_b = 8, 30, 26, 24
    xs = [pad_l + i * (width - pad_l - pad_r) / (len(series) - 1) for i in range(len(series))]
    vals = [v for _, v in series]
    lo, hi = min(vals), max(vals)
    span = (hi - lo) or 0.05
    lo, hi = lo - span * 0.18, hi + span * 0.18
    ys = [pad_t + (hi - v) / (hi - lo) * (height - pad_t - pad_b) for v in vals]
    pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in zip(xs, ys))
    area = f"{xs[0]:.1f},{height - pad_b} {pts} {xs[-1]:.1f},{height - pad_b}"

    labels = []
    for i, ((date, _), x) in enumerate(zip(series, xs)):
        anchor = "start" if i == 0 else ("end" if i == len(series) - 1 else "middle")
        labels.append(f'<text x="{x:.1f}" y="{height - 6}" text-anchor="{anchor}" '
                      f'font-size="9" fill="{t["date_lab"]}" '
                      f'font-family="Work Sans,sans-serif">{_short_date(date)}</text>')
    # Selective direct labels: first and last value only, in text ink.
    labels.append(f'<text x="{xs[0]:.1f}" y="{ys[0] - 9:.1f}" text-anchor="start" '
                  f'font-size="10" fill="{t["val_first"]}" '
                  f'font-family="Work Sans,sans-serif">{vals[0]:.2f}</text>')
    labels.append(f'<text x="{xs[-1] + 6:.1f}" y="{ys[-1] + 3:.1f}" text-anchor="start" '
                  f'font-size="11" font-weight="600" fill="{t["val_last"]}" '
                  f'font-family="Work Sans,sans-serif">{vals[-1]:.2f}</text>')

    return f'''<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" fill="none">
  <defs>
    <linearGradient id="fill" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="{t["fill_top"]}"/>
      <stop offset="100%" stop-color="rgba(255,255,255,0)"/>
    </linearGradient>
  </defs>
  <line x1="{pad_l}" y1="{height - pad_b}" x2="{width - pad_r}" y2="{height - pad_b}"
        stroke="{t["axis"]}" stroke-width="1"/>
  <polygon points="{area}" fill="url(#fill)"/>
  <polyline points="{pts}" stroke="{t["line"]}" stroke-width="2"
            stroke-linecap="round" stroke-linejoin="round"/>
  <circle cx="{xs[-1]:.1f}" cy="{ys[-1]:.1f}" r="7" fill="{t["halo"]}"/>
  <circle cx="{xs[-1]:.1f}" cy="{ys[-1]:.1f}" r="4" fill="{t["dot"]}"/>
  {"".join(labels)}
</svg>'''


def build_html(series, last, prev, as_of, source, t):
    delta_bps = round((last - prev) * 100)
    if delta_bps > 0:
        arrow, color, word = "&#9650;", t["up"], "up"       # ▲
    elif delta_bps < 0:
        arrow, color, word = "&#9660;", t["down"], "down"   # ▼
    else:
        arrow, color, word = "&#9654;", t["flat"], "unchanged"
    change = (f'<span style="color:{color};font-size:22px;">{arrow}</span>'
              f'<span class="sans" style="font-size:15px;font-weight:600;color:{color};">'
              f'{abs(delta_bps)} bps {word}</span>'
              f'<span class="sans" style="font-size:13px;color:{t["vs"]};">'
              f'vs previous close</span>')

    heading = gc.h_light if t["on_light"] else gc.h_dark
    content = (
        gc.logo_lockup(t["on_light"])
        + gc.tag("Market Pulse", t["tag_bg"])
        + heading("10-Year Treasury", 30)
        + f'<div style="display:flex;align-items:baseline;gap:14px;margin:2px 0 4px;">'
          f'<span class="serif" style="font-size:64px;font-weight:700;color:{t["hero"]};'
          f'letter-spacing:-2px;line-height:1;">{last:.2f}%</span>'
          f'<span style="display:inline-flex;align-items:center;gap:7px;">{change}</span></div>'
        + f'<p class="sans" style="font-size:11px;color:{t["kicker"]};'
          f'letter-spacing:1px;text-transform:uppercase;margin:14px 0 6px;">Last {len(series)} trading days</p>'
        + build_chart_svg(series, t)
        + f'<p class="sans" style="font-size:10px;color:{t["footer"]};margin-top:16px;">'
          f'As of {as_of} &mdash; {source}</p>'
    )

    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>10-Year Treasury</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=Libre+Baskerville:ital,wght@0,400;0,700;1,400&family=Work+Sans:wght@400;500;600;700&display=swap');
*{{margin:0;padding:0;box-sizing:border-box;}}
body{{margin:0;font-family:'Work Sans',sans-serif;}}
.serif{{font-family:'Libre Baskerville',serif;}}
.sans{{font-family:'Work Sans',sans-serif;}}
.slide{{width:420px;height:525px;background:{t["bg"]};overflow:hidden;position:relative;}}
.slide-content{{height:100%;display:flex;flex-direction:column;justify-content:center;padding:0 36px;position:relative;z-index:2;}}
</style></head><body>
<div class="slide"><div class="slide-content">{content}</div></div>
</body></html>"""


def export_png(html_path, png_path):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 420, "height": 525},
                                device_scale_factor=1080 / 420)
        page.goto(html_path.resolve().as_uri())
        page.wait_for_timeout(2500)  # let Google Fonts load
        page.screenshot(path=str(png_path),
                        clip={"x": 0, "y": 0, "width": 420, "height": 525})
        browser.close()


def pick_theme():
    """The card takes the day's MINORITY carousel-cover colour: even ordinal days
    render 2 blue covers + 1 white (see generate_carousels.main), so the card
    goes white; odd days it's the other way round. A CLI arg ("light"/"dark")
    overrides for testing."""
    if len(sys.argv) > 1 and sys.argv[1] in THEMES:
        return sys.argv[1]
    blue_covers = 2 if gc._TODAY.toordinal() % 2 == 0 else 1
    return "light" if blue_covers == 2 else "dark"


def main():
    theme = pick_theme()
    series, last, prev, as_of, source = get_data()
    html_path = BASE / "carousels" / "treasury.html"
    png_path = BASE / "carousels" / "slides" / "treasury.png"
    png_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.write_text(build_html(series, last, prev, as_of, source, THEMES[theme]),
                         encoding="utf-8")
    export_png(html_path, png_path)
    print(f"Wrote {html_path.relative_to(BASE)} and {png_path.relative_to(BASE)} "
          f"[{theme} theme] ({last:.2f}%, {round((last - prev) * 100):+d} bps, "
          f"as of {as_of})")


if __name__ == "__main__":
    main()
