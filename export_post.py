"""
Export post.html (stacked 420x525 Kickoff News slides) to 1080x1350 PNGs using
Playwright — one PNG per slide.
    pip install playwright && playwright install chromium
Run:  python export_post.py
Output: posts/kickoff_1.png, posts/kickoff_2.png, ...
"""
import asyncio
from pathlib import Path

from playwright.async_api import async_playwright

BASE = Path(__file__).parent
SRC = BASE / "post.html"
OUT_DIR = BASE / "posts"
VIEW_W, VIEW_H = 420, 525
SCALE = 1080 / 420  # -> 1080x1350 per slide


async def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={"width": VIEW_W, "height": VIEW_H * 6},
                                      device_scale_factor=SCALE)
        await page.set_content(SRC.read_text(encoding="utf-8"), wait_until="networkidle")
        await page.wait_for_timeout(3000)  # let fonts + images settle
        total = await page.evaluate("() => document.querySelectorAll('.slide').length")
        for i in range(total):
            await page.screenshot(path=str(OUT_DIR / f"kickoff_{i+1}.png"),
                                  clip={"x": 0, "y": i * VIEW_H, "width": VIEW_W, "height": VIEW_H})
            print(f"  wrote posts/kickoff_{i+1}.png")
        await browser.close()
    print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
