"""Shoot preview.png for the 001-linear-dark prototype."""
from pathlib import Path
from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
url = (HERE / "index.html").as_uri()
out = HERE / "preview.png"

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    page.goto(url, wait_until="load")
    page.wait_for_timeout(700)

    # Basic layout sanity checks
    title = page.title()
    grid_ok = page.evaluate("document.querySelector('.grid').getBoundingClientRect().width > 800")
    cards = page.evaluate("document.querySelectorAll('.card:not(.gone)').length")
    bar_visible = page.evaluate(
        "getComputedStyle(document.getElementById('selbar')).display !== 'none'"
    )
    font_ok = page.evaluate(
        "document.fonts.check('14px Inter') || document.fonts.status === 'loaded'"
    )
    print(f"title={title!r} cards={cards} grid_ok={grid_ok} bar_visible={bar_visible} font_ok={font_ok}")

    page.screenshot(path=str(out), full_page=False)
    browser.close()

print(f"saved {out}")
