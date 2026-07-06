"""
Export each carousel's slides as Instagram-ready 1080x1350 PNGs.

The carousels are designed at 420px wide (4:5 = 525px tall). We keep that layout
width and use Playwright's device_scale_factor to scale up to 1080px output WITHOUT
reflowing the layout.  Setup:
    pip install playwright
    playwright install chromium
Run:
    python export_slides.py
Output: carousels/slides/<carousel_name>/slide_1.png ... slide_7.png
"""
import asyncio
from pathlib import Path
from playwright.async_api import async_playwright

BASE = Path(__file__).parent / "carousels"
CAROUSELS = [
    "carousel_1.html",
    "carousel_2.html",
    "carousel_3.html",
]

VIEW_W = 420
VIEW_H = 525
SCALE = 1080 / 420  # 2.5714 -> 1080x1350 output

async def export_one(browser, filename):
    name = Path(filename).stem
    out_dir = BASE / "slides" / name
    out_dir.mkdir(parents=True, exist_ok=True)

    page = await browser.new_page(
        viewport={"width": VIEW_W, "height": VIEW_H},
        device_scale_factor=SCALE,
    )
    html = (BASE / filename).read_text(encoding="utf-8")
    await page.set_content(html, wait_until="networkidle")
    await page.wait_for_timeout(3000)  # let Google Fonts load

    total = await page.evaluate("() => document.querySelectorAll('.slide').length")

    # Strip the IG frame chrome, show only the 420x525 slide viewport
    await page.evaluate("""() => {
        document.querySelectorAll('.ig-header,.ig-dots,.ig-actions,.ig-caption')
            .forEach(el => el.style.display='none');
        const frame = document.querySelector('.ig-frame');
        frame.style.cssText = 'width:420px;height:525px;max-width:none;border-radius:0;box-shadow:none;overflow:hidden;margin:0;';
        const viewport = document.querySelector('.carousel-viewport');
        viewport.style.cssText = 'width:420px;height:525px;aspect-ratio:unset;overflow:hidden;cursor:default;';
        document.body.style.cssText = 'padding:0;margin:0;display:block;overflow:hidden;';
    }""")
    await page.wait_for_timeout(500)

    for i in range(total):
        await page.evaluate("""(idx) => {
            const track = document.querySelector('.carousel-track');
            track.style.transition = 'none';
            track.style.transform = 'translateX(' + (-idx * 420) + 'px)';
        }""", i)
        await page.wait_for_timeout(400)
        await page.screenshot(
            path=str(out_dir / f"slide_{i+1}.png"),
            clip={"x": 0, "y": 0, "width": VIEW_W, "height": VIEW_H},
        )
        print(f"  {name}: slide {i+1}/{total}")
    await page.close()

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        for filename in CAROUSELS:
            print(f"Exporting {filename} ...")
            await export_one(browser, filename)
        await browser.close()
    print("Done. PNGs in carousels/slides/<name>/")

if __name__ == "__main__":
    asyncio.run(main())
