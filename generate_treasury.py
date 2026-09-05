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
import time
import urllib.request
from pathlib import Path

# Reuse the carousel design system: brand tokens, masthead, fonts, gradients.
import generate_carousels as gc

BASE = Path(__file__).parent
DAYS = 7
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

CNBC_URL = ("https://quote.cnbc.com/quote-html-webservice/restQuote/symbolType/symbol"
            "?symbols=US10Y&requestMethod=itv&noform=1&partnerId=2&fund=1&exthrs=1&output=json")
# Two Yahoo hosts — CI runners occasionally get rate-limited on one of them.
YAHOO_URLS = ["https://query1.finance.yahoo.com/v8/finance/chart/%5ETNX?range=1mo&interval=1d",
              "https://query2.finance.yahoo.com/v8/finance/chart/%5ETNX?range=1mo&interval=1d"]
FRED_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS10"

# The 6am quote snapshot. The workflow saves and commits it in a tiny early step,
# so if the run fails and a retry (or a manual re-run) fires later, the card
# still shows the 6am value — the number stays consistent however many times the
# card is regenerated that day. `python generate_treasury.py live` overrides.
SNAPSHOT = Path(__file__).parent / "treasury_snapshot.json"

# Accumulated 6:00 AM ET values, one per trading day — the chart plots THESE
# (not daily closes). Each morning's snapshot records the exact 6am quote;
# missing days are backfilled from CNBC's 5-minute intraday bars (5D window).
HISTORY = Path(__file__).parent / "treasury_history.json"
CNBC_5D_URL = "https://ts-api.cnbc.com/harmony/app/charts/5D.json?symbol=US10Y"


def _load_history():
    try:
        return json.loads(HISTORY.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 — missing/corrupt file means empty history
        return {}


def _record_history(date, value, src):
    """Store a day's 6am value. A real snapshot always wins over a backfill."""
    hist = _load_history()
    entry = hist.get(date)
    if entry and entry.get("src") == "snapshot" and src != "snapshot":
        return
    hist[date] = {"value": round(float(value), 3), "src": src}
    HISTORY.write_text(json.dumps(hist, indent=1, sort_keys=True), encoding="utf-8")


_BARS_CACHE = None


def _cnbc_bars():
    """CNBC's 5-minute intraday bars for the last ~5 sessions (ET timestamps),
    fetched once per run."""
    global _BARS_CACHE
    if _BARS_CACHE is None:
        _BARS_CACHE = json.loads(_get(CNBC_5D_URL))["barData"]["priceBars"]
    return _BARS_CACHE


def six_am_today_value():
    """The market's level at 6:00 AM ET TODAY: the newest intraday bar at or
    before 06:00. On weekends/holidays (no bars today) that is the prior
    session's close — which is exactly what the yield stood at, at 6am."""
    cutoff = _today_et().replace("-", "") + "0600"
    best = None
    for b in _cnbc_bars():
        tt = str(b.get("tradeTime", ""))[:12]
        if len(tt) == 12 and tt <= cutoff and (best is None or tt > best[0]):
            best = (tt, float(b["close"]))
    return best[1] if best else None


def _pin_to_6am(live):
    """Re-anchor a (last, prev, as_of) quote to today's 6:00 AM ET level — the
    number the card shows must always be the morning value for the CURRENT day,
    never the current quote or a prior day's closing time."""
    v6 = _retry(six_am_today_value, "CNBC 6am bar")
    if v6 is None:
        return live
    d = _today_et()
    return (v6, live[1], f"{int(d[5:7])}/{int(d[8:10])}/{d[:4]} 6:00 AM ET")


def fetch_cnbc_6am_history():
    """{iso_date: value} of ~6:00 AM ET prints from CNBC's 5-day intraday bars
    (tradeTime strings are ET). Takes the bar closest to 6:00, within 90 min."""
    bars = _cnbc_bars()
    best = {}
    for b in bars:
        tt = str(b.get("tradeTime", ""))
        if len(tt) != 14:
            continue
        date = f"{tt[0:4]}-{tt[4:6]}-{tt[6:8]}"
        dist = abs(int(tt[8:10]) * 60 + int(tt[10:12]) - 360)  # minutes from 6:00
        if dist <= 90 and (date not in best or dist < best[date][0]):
            best[date] = (dist, float(b["close"]))
    return {d: v for d, (_, v) in best.items()}


def build_6am_series():
    """Last DAYS trading days as [(iso_date, 6am value)]: snapshots first,
    CNBC intraday backfill second, Yahoo daily closes as a last resort for
    dates outside CNBC's 5-day window."""
    for d, v in (_retry(fetch_cnbc_6am_history, "CNBC 6am history") or {}).items():
        _record_history(d, v, "cnbc-6am")
    hist = _load_history()
    ycloses = dict(_retry(fetch_yahoo, "Yahoo history") or [])
    series = []
    cur = datetime.date.fromisoformat(_today_et())
    for _ in range(15):  # scan back far enough to find DAYS weekdays with data
        d = cur.isoformat()
        if cur.weekday() < 5:
            v = hist.get(d, {}).get("value", ycloses.get(d))
            if v is not None:
                series.append((d, float(v)))
            if len(series) == DAYS:
                break
        cur -= datetime.timedelta(days=1)
    series.reverse()
    return series


def _today_et():
    try:
        from zoneinfo import ZoneInfo
        return datetime.datetime.now(ZoneInfo("America/New_York")).date().isoformat()
    except Exception:  # noqa: BLE001 — local clock is close enough as a fallback
        return datetime.date.today().isoformat()


def save_snapshot():
    """Snapshot mode: record the current CNBC quote for today, once. Later calls
    the same day (retry runs) keep the earliest snapshot."""
    if SNAPSHOT.exists():
        try:
            if json.loads(SNAPSHOT.read_text(encoding="utf-8")).get("date") == _today_et():
                print("Snapshot for today already exists — keeping it.")
                return
        except Exception:  # noqa: BLE001 — overwrite a corrupt snapshot
            pass
    live = _retry(fetch_cnbc, "CNBC quote")
    if live is None:
        print("WARNING: could not snapshot the treasury quote (CNBC down).")
        return
    last, prev, as_of = _pin_to_6am(live)
    SNAPSHOT.write_text(json.dumps({"date": _today_et(), "last": last, "prev": prev,
                                    "as_of": as_of}), encoding="utf-8")
    _record_history(_today_et(), last, "snapshot")
    print(f"Snapshot saved: {last:.2f}% as of {as_of}")


def load_snapshot():
    """Today's snapshot as (last, prev, as_of), or None."""
    try:
        snap = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
        if snap.get("date") == _today_et():
            return float(snap["last"]), float(snap["prev"]), str(snap["as_of"])
    except Exception:  # noqa: BLE001 — missing/corrupt snapshot means none
        pass
    return None


def _retry(fn, name, attempts=3, delay=8):
    """Run fn() up to `attempts` times with growing waits. Returns its value or
    None — transient quote-API hiccups must never take the card (or the whole
    6am run) down."""
    for i in range(1, attempts + 1):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 — sources fail over
            print(f"{name} attempt {i}/{attempts} failed: {str(exc)[:120]}")
            if i < attempts:
                time.sleep(delay * i)
    return None

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
    """Live US10Y quote. Returns (last, previous_close, as_of_text). Raises on
    failure — callers wrap with _retry."""
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


def fetch_yahoo(days=DAYS):
    """Last `days` daily closes from Yahoo ^TNX (includes today's intraday bar).
    Tries both Yahoo hosts. Raises if neither returns usable data."""
    last_exc = None
    for url in YAHOO_URLS:
        try:
            res = json.loads(_get(url))["chart"]["result"][0]
            closes = res["indicators"]["quote"][0]["close"]
            pairs = [(datetime.datetime.fromtimestamp(t).strftime("%Y-%m-%d"), round(c, 3))
                     for t, c in zip(res["timestamp"], closes) if c is not None]
            if len(pairs) >= 2:
                return pairs[-days:]
            raise ValueError(f"only {len(pairs)} usable closes")
        except Exception as exc:  # noqa: BLE001 — try the next host
            last_exc = exc
    raise last_exc


def fetch_fred(days=DAYS):
    """Last `days` daily closes from FRED DGS10 (keyless CSV, ~1-2 days behind)."""
    lines = _get(FRED_URL).decode("utf-8").strip().splitlines()
    series = []
    for line in lines[1:]:
        date, value = line.split(",")
        if value not in (".", ""):
            series.append((date, float(value)))
    return series[-days:]


def get_data(mode="live"):
    """Returns (series, last, prev, as_of, source_label) or None if every source
    is down (the card is then skipped without failing the daily run).
    mode "snapshot" (scheduled 6am runs and their retries): the headline number
    comes from today's committed 6am snapshot, so a 9am retry still shows the
    6am value. mode "live" (manual runs): always the current quote."""
    live = load_snapshot() if mode == "snapshot" else None
    if live:
        print(f"Using today's 6am snapshot: {live[0]:.2f}% as of {live[2]}")
    else:
        live = _retry(fetch_cnbc, "CNBC quote")
        if live and mode == "snapshot":
            # No snapshot yet today (a late or weekend run). Pin the headline to
            # TODAY's 6:00 AM ET level from the intraday bars — never the
            # current quote or the prior day's closing time — and record it so
            # every later run today shows the same number.
            live = _pin_to_6am(live)
            print(f"Pinned to today's 6:00 AM ET level: {live[0]:.2f}%")
            SNAPSHOT.write_text(json.dumps({"date": _today_et(), "last": live[0],
                                            "prev": live[1], "as_of": live[2]}),
                                encoding="utf-8")
            _record_history(_today_et(), live[0], "snapshot")
    series = build_6am_series()
    source = "6:00 AM ET values &mdash; Source: CNBC (US10Y)"
    if len(series) < 2:
        series = _retry(fetch_fred, "FRED history")
        source = "Daily closes &mdash; Source: FRED (DGS10)"
    if series is None or len(series) < 2:
        return None
    if live:
        last, prev, as_of = live
        # Keep the chart's newest point in sync with the headline number
        # (weekend runs chart through Friday, so only sync a same-day point).
        if series[-1][0] == _today_et():
            series[-1] = (series[-1][0], last)
    else:
        last, prev = series[-1][1], series[-2][1]
        as_of = _short_date(series[-1][0]) + f"/{series[-1][0][:4]}"
    return series, last, prev, as_of, source


def build_caption(series, last, prev, as_of):
    """Email/posting commentary: today's move in bps plus the week's trend."""
    d_today = round((last - prev) * 100)
    week_delta = round((last - series[0][1]) * 100)
    span = f"{series[0][1]:.2f}% on {_short_date(series[0][0])} to {last:.2f}%"
    if d_today > 0:
        today_txt = f"up {d_today} bps from the previous close"
    elif d_today < 0:
        today_txt = f"down {abs(d_today)} bps from the previous close"
    else:
        today_txt = "unchanged from the previous close"
    if week_delta > 2:
        week_txt = f"This week it has been trending up: +{week_delta} bps ({span})."
    elif week_delta < -2:
        week_txt = f"This week it has been trending down: {week_delta} bps ({span})."
    else:
        week_txt = (f"This week it has been roughly flat: {week_delta:+d} bps ({span}).")
    return (f"The 10-Year Treasury is at {last:.2f}%, {today_txt} (as of {as_of}). "
            f"{week_txt}")


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

    labels, dots = [], []
    n = len(series)
    for i, ((date, v), x, y) in enumerate(zip(series, xs, ys)):
        anchor = "start" if i == 0 else ("end" if i == n - 1 else "middle")
        labels.append(f'<text x="{x:.1f}" y="{height - 6}" text-anchor="{anchor}" '
                      f'font-size="9" fill="{t["date_lab"]}" '
                      f'font-family="Work Sans,sans-serif">{_short_date(date)}</text>')
        # A marker on every point — each is that day's 6:00 AM ET value — with
        # its value labelled above; the newest point keeps the big accent dot.
        if i < n - 1:
            dots.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3" fill="{t["dot"]}"/>')
            labels.append(f'<text x="{x:.1f}" y="{y - 9:.1f}" text-anchor="middle" '
                          f'font-size="9" fill="{t["val_first"]}" '
                          f'font-family="Work Sans,sans-serif">{v:.2f}</text>')
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
  {"".join(dots)}
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
          f'letter-spacing:1px;text-transform:uppercase;margin:14px 0 6px;">'
          f'Last {len(series)} trading days &mdash; 6:00 AM ET</p>'
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


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "snapshot":
        save_snapshot()
        return

    # Every run — scheduled, retried, or manual — pins the headline to today's
    # 6am snapshot so the posted card stays consistent all day. If no snapshot
    # exists yet, the live quote is used and becomes today's snapshot. Pass
    # "live" to force the current quote instead.
    mode = "live" if (len(sys.argv) > 1 and sys.argv[1] == "live") else "snapshot"
    print(f"Treasury card mode: {mode}")
    data = get_data(mode)
    if data is None:
        # Every source down after retries: keep the previous day's committed
        # card rather than failing the whole 6am run over a market-data outage.
        print("WARNING: all 10Y treasury sources failed — skipping the card today.")
        return
    series, last, prev, as_of, source = data

    # Both colour variants every day; the (also committed) HTML is the source
    # the PNGs are screenshotted from.
    slides_dir = BASE / "carousels" / "slides"
    slides_dir.mkdir(parents=True, exist_ok=True)
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 420, "height": 525},
                                device_scale_factor=1080 / 420)
        for theme in ("light", "dark"):
            html_path = BASE / "carousels" / f"treasury_{theme}.html"
            png_path = slides_dir / f"treasury_{theme}.png"
            html_path.write_text(
                build_html(series, last, prev, as_of, source, THEMES[theme]),
                encoding="utf-8")
            page.goto(html_path.resolve().as_uri())
            page.wait_for_timeout(2500)  # let Google Fonts load
            page.screenshot(path=str(png_path),
                            clip={"x": 0, "y": 0, "width": 420, "height": 525})
            print(f"Wrote carousels/treasury_{theme}.html and "
                  f"carousels/slides/treasury_{theme}.png")
        browser.close()

    caption = build_caption(series, last, prev, as_of)
    (BASE / "carousels" / "treasury_caption.txt").write_text(caption + "\n",
                                                             encoding="utf-8")
    print(f"Caption: {caption}")


if __name__ == "__main__":
    main()
