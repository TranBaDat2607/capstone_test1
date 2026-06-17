#!/usr/bin/env python3
"""
Stage 3 - Download the sector-specific Vietnamese sources used to tailor the KPI
set to Construction / Building Materials / Real Estate.

Each document has several candidate mirror URLs (some legal portals return HTTP
403 to scripts, others return only navigation boilerplate); we save the first
mirror whose HTML actually contains the document body (`must_contain`). The
SSC-IFC guide is already downloaded by Stage 1.

Run:
    python 03_download_sector_sources.py
"""

import hashlib
import json
import pathlib
import unicodedata

import requests
from bs4 import BeautifulSoup

HERE = pathlib.Path(__file__).resolve().parent
SOURCES_DIR = HERE / "sources"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "vi,en;q=0.9",
}

# Each source lists mirror URLs in priority order.
SECTOR_SOURCES = [
    {
        "id": "QD_2171_2021",
        "title": "Quyet dinh 2171/QD-TTg (2021) - Chuong trinh phat trien vat lieu "
                 "xay khong nung tai Viet Nam den nam 2030",
        "publisher": "Thu tuong Chinh phu",
        "filename": "QD_2171_2021.html",
        # Require the actual objectives text (a target percentage), not metadata.
        "must_contain": "tổng số vật liệu xây",
        "urls": [
            "https://hethongphapluat.com/quyet-dinh-2171-qd-ttg-nam-2021-phe-duyet-chuong-trinh-phat-trien-vat-lieu-xay-khong-nung-tai-viet-nam-den-nam-2030-do-thu-tuong-chinh-phu-ban-hanh/dieu-1",
            "https://lawnet.vn/vb/Quyet-dinh-2171-QD-TTg-2021-Chuong-trinh-phat-trien-vat-lieu-xay-khong-nung-tai-Viet-Nam-79AD6.html",
            "https://luatvietnam.vn/xay-dung/quyet-dinh-2171-qd-ttg-214583-d1.html",
        ],
    },
    {
        "id": "QCVN_09_2017",
        "title": "QCVN 09:2017/BXD - Quy chuan ky thuat quoc gia ve cac cong trinh "
                 "xay dung su dung nang luong hieu qua",
        "publisher": "Bo Xay dung",
        "filename": "QCVN_09_2017.html",
        "must_contain": "năng lượng hiệu quả",
        "urls": [
            "https://hethongphapluat.com/quy-chuan-ky-thuat-quoc-gia-qcvn-09-2017-bxd-ve-cac-cong-trinh-xay-dung-su-dung-nang-luong-hieu-qua.html",
            "https://vanbanphapluat.co/qcvn-09-2017-bxd-cong-trinh-xay-dung-su-dung-nang-luong-hieu-qua",
        ],
    },
]


def page_contains(content: bytes, needle: str) -> bool:
    text = unicodedata.normalize("NFC", BeautifulSoup(content, "html.parser").get_text(" "))
    return needle.lower() in text.lower()


def fetch_first_ok(urls: list[str], must_contain: str) -> tuple[str, bytes, int] | None:
    for url in urls:
        try:
            r = requests.get(url, headers=HEADERS, timeout=40)
            has = r.status_code == 200 and page_contains(r.content, must_contain)
            print(f"      try {r.status_code}  contains[{must_contain}]={has}  {url[:60]}")
            if has:
                return url, r.content, r.status_code
        except Exception as exc:  # noqa: BLE001
            print(f"      ERR {type(exc).__name__} {url[:60]}")
    return None


def main() -> None:
    SOURCES_DIR.mkdir(parents=True, exist_ok=True)
    manifest_path = SOURCES_DIR / "manifest_sector.json"
    manifest = []
    for src in SECTOR_SOURCES:
        print(f"[..]  {src['id']}")
        got = fetch_first_ok(src["urls"], src["must_contain"])
        rec = {k: src[k] for k in ("id", "title", "publisher", "filename")}
        if got:
            url, content, status = got
            (SOURCES_DIR / src["filename"]).write_bytes(content)
            rec.update({
                "used_url": url, "http_status": status, "bytes": len(content),
                "sha256": hashlib.sha256(content).hexdigest(), "ok": True,
            })
            print(f"[OK]  {src['id']}: {len(content):,} bytes -> {src['filename']}")
        else:
            rec["ok"] = False
            print(f"[FAIL] {src['id']}: no mirror returned readable content")
        manifest.append(rec)

    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2),
                             encoding="utf-8")
    print(f"\nManifest: {manifest_path}")


if __name__ == "__main__":
    main()
