"""
FPT Annual Report Crawler
Uses nodriver (undetected Chrome) to bypass Cloudflare.
Disables Chrome's PDF viewer so navigating to a PDF triggers a file download.
"""
import asyncio
import json
import os
import re
import shutil
import tempfile
import time
from pathlib import Path

import nodriver as uc
import nodriver.cdp.browser as cdp_browser

BASE_URL = "https://fpt.com"
REPORT_URL = f"{BASE_URL}/en/ir/report"
OUTPUT_DIR = Path(__file__).parent / "crawl_data"

ANNUAL_REPORT_PATTERNS = [
    r"/ir/general-meetings-of-shareholders/.*annual.*\.pdf",
    r"/ir/report/tabs/annual-report/.*\.pdf",
    r"/ir/common/file/.*ar-fpt.*\.pdf",
    r"/ir/general-meetings-of-shareholders/.*esg.*\.pdf",
]


def is_annual_report(href: str) -> bool:
    return any(re.search(p, href.lower()) for p in ANNUAL_REPORT_PATTERNS)


def safe_filename(href: str) -> str:
    name = href.rstrip("/").split("/")[-1].split("?")[0]
    if not name.lower().endswith(".pdf"):
        name += ".pdf"
    return re.sub(r'[<>:"|?*]', "_", name)


def make_chrome_profile(download_dir: str) -> str:
    """
    Create a temporary Chrome user data dir with:
    - PDFs always downloaded (not opened in viewer)
    - Auto-download to download_dir
    """
    profile_dir = tempfile.mkdtemp(prefix="fpt_crawler_profile_")
    default_dir = os.path.join(profile_dir, "Default")
    os.makedirs(default_dir, exist_ok=True)

    prefs = {
        "plugins": {
            "always_open_pdf_externally": True,
        },
        "download": {
            "default_directory": download_dir,
            "prompt_for_download": False,
            "directory_upgrade": True,
        },
        "safebrowsing": {
            "enabled": False,
        },
    }
    prefs_path = os.path.join(default_dir, "Preferences")
    with open(prefs_path, "w") as f:
        json.dump(prefs, f)

    return profile_dir


def wait_for_pdf(directory: Path, known_files: set, timeout: float = 60) -> Path | None:
    """Wait for a new completed .pdf file to appear in directory."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        # Wait for crdownload to disappear first (download in progress)
        current_pdfs = {
            f for f in directory.iterdir()
            if f.is_file() and f.suffix.lower() == ".pdf"
        }
        new_pdfs = current_pdfs - known_files
        if new_pdfs:
            # Make sure file is not still being written
            f = list(new_pdfs)[0]
            time.sleep(0.5)
            if f.exists() and f.stat().st_size > 0:
                return f
        time.sleep(0.5)
    return None


async def crawl():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    profile_dir = make_chrome_profile(str(OUTPUT_DIR.resolve()))
    try:
        browser = await uc.start(
            headless=False,
            user_data_dir=profile_dir,
        )
        tab = await browser.get(REPORT_URL)

        try:
            # Wait for Cloudflare challenge
            print(f"Loading {REPORT_URL} ...")
            for _ in range(30):
                title = await tab.evaluate("document.title")
                if title and "just a moment" not in title.lower():
                    break
                print(f"  Waiting for Cloudflare... ({title})")
                await asyncio.sleep(1)

            await asyncio.sleep(3)
            print(f"Page ready: {await tab.evaluate('document.title')}")

            # Tell Chrome to save downloads to OUTPUT_DIR
            await tab.send(cdp_browser.set_download_behavior(
                behavior="allow",
                download_path=str(OUTPUT_DIR.resolve()),
            ))

            # Extract PDF hrefs from rendered HTML
            html = await tab.evaluate("document.documentElement.outerHTML")
            all_hrefs = re.findall(r'href="(/[^"]+\.pdf)"', html, re.IGNORECASE)

            seen: set[str] = set()
            annual_hrefs: list[str] = []
            for h in all_hrefs:
                if h not in seen:
                    seen.add(h)
                    if is_annual_report(h):
                        annual_hrefs.append(h)

            print(f"Found {len(annual_hrefs)} annual/ESG report PDF(s):\n")
            for h in annual_hrefs:
                print(f"  {h}")
            print()

            ok_count = 0
            for href in annual_hrefs:
                url = BASE_URL + href
                filename = safe_filename(href)
                dest = OUTPUT_DIR / filename

                if dest.exists() and dest.stat().st_size > 1000:
                    print(f"  [skip] {filename}  ({dest.stat().st_size // 1024} KB)")
                    ok_count += 1
                    continue

                known_pdfs = {
                    f for f in OUTPUT_DIR.iterdir()
                    if f.is_file() and f.suffix.lower() == ".pdf"
                }
                print(f"  [down] {filename} ...")

                # Navigate to PDF URL — Chrome will download it (PDF viewer disabled)
                await tab.get(url)

                # Wait for the download to appear
                new_file = wait_for_pdf(OUTPUT_DIR, known_pdfs, timeout=60)

                if new_file:
                    # Rename to expected name if needed
                    if new_file.name != dest.name:
                        new_file.rename(dest)
                    # Wait for any in-progress write to finish
                    for _ in range(10):
                        await asyncio.sleep(1)
                        if dest.exists() and dest.stat().st_size > 0:
                            # Check no crdownload sibling
                            crdownload = dest.with_suffix(".crdownload")
                            if not crdownload.exists():
                                break

                    size_kb = dest.stat().st_size // 1024 if dest.exists() else 0
                    print(f"         saved ({size_kb} KB)")
                    ok_count += 1
                else:
                    print(f"         FAILED (download timeout)")

                # Return to report page for next iteration
                await tab.get(REPORT_URL)
                await asyncio.sleep(2)

            print(f"\nDone. {ok_count}/{len(annual_hrefs)} file(s) in '{OUTPUT_DIR}'.")

        finally:
            browser.stop()

    finally:
        shutil.rmtree(profile_dir, ignore_errors=True)


if __name__ == "__main__":
    asyncio.run(crawl())
