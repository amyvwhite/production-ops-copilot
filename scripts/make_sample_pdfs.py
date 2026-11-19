"""Print the issued sample call sheets to PDF (sample_data/pdfs/), for the upload demo and
the extraction eval. Needs Playwright + Chromium (dev only):

    pip install playwright && playwright install chromium
    python scripts/make_sample_pdfs.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.documents import render_call_sheet  # noqa: E402
from app.loader import demo_today, load_production  # noqa: E402

DATA = ROOT / "sample_data"
OUT = DATA / "pdfs"


async def main() -> None:
    from playwright.async_api import async_playwright

    prod = load_production(DATA)
    today = demo_today(DATA)
    OUT.mkdir(exist_ok=True)
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        for sheet in prod.call_sheets:
            await page.set_content(render_call_sheet(prod, sheet.date, today, flags=False))
            path = OUT / f"call_sheet_{sheet.date}.pdf"
            await page.pdf(path=str(path), format="Letter", print_background=True)
            print("wrote", path.relative_to(ROOT))
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
