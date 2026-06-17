#!/usr/bin/env python3
"""
Stage 1 - Download the official Vietnamese regulatory ESG sources.

These are the authoritative documents the KPI definitions are derived from.
Everything is saved verbatim into ./sources so the extraction stage is fully
reproducible and auditable (no LLM-generated content at this step).

Run:
    python 01_download_sources.py
"""

import hashlib
import json
import pathlib

import requests

HERE = pathlib.Path(__file__).resolve().parent
SOURCES_DIR = HERE / "sources"

# Browser-like headers - the government / legal portals reject the default
# python-requests user agent with HTTP 403.
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "vi,en;q=0.9",
}

# Each source records WHERE it comes from so provenance is traceable.
SOURCES = [
    {
        "id": "TT96_2020",
        "title": "Thong tu 96/2020/TT-BTC - huong dan cong bo thong tin tren "
                 "thi truong chung khoan (Cong bao Chinh phu, ban goc)",
        "publisher": "Bo Tai chinh / Cong bao Chinh phu",
        "url": "https://congbao.chinhphu.vn/noi-dung-van-ban-so-96-2020-tt-btc-32793",
        "filename": "TT96_2020_congbao.html",
        "kind": "html",
    },
    {
        "id": "TT96_2020_TEMPLATE",
        "title": "Mau Bao cao thuong nien ban hanh kem theo Thong tu 96/2020/TT-BTC "
                 "(Phu luc IV) - ban tra cuu",
        "publisher": "LuatMinhKhue (tra cuu Phu luc IV)",
        "url": "https://luatminhkhue.vn/mau-bao-cao-thuong-nien-ban-hanh-theo-thong-tu-so-96-2020-tt-btc.aspx",
        "filename": "TT96_2020_phuluc4.html",
        "kind": "html",
    },
    {
        "id": "SSC_IFC_GUIDE",
        "title": "Huong dan lap Bao cao Phat trien ben vung (SSC - IFC)",
        "publisher": "Uy ban Chung khoan Nha nuoc (SSC) & IFC",
        "url": ("https://ssc.gov.vn/webcenter/contentattachfile/idcplg?"
                "IdcService=GET_FILE&allowInterrupt=1&dID=113962"
                "&dDocName=APPSSCGOVVN162078672"
                "&Rendition=SSC+IFC+Huong+dan+lap+Bao+cao+Phat+trien+ben+vung.pdf"
                "&filename=SSC+IFC+Huong+dan+lap+Bao+cao+Phat+trien+ben+vung.pdf"
                "&IsAttachment=1"),
        "filename": "SSC_IFC_sustainability_guide.pdf",
        "kind": "pdf",
    },
]


def download_one(src: dict) -> dict:
    """Download a single source, save it, and return a manifest record."""
    out_path = SOURCES_DIR / src["filename"]
    record = {**src, "saved_as": str(out_path.relative_to(HERE))}
    try:
        resp = requests.get(src["url"], headers=HEADERS, timeout=40)
        record["http_status"] = resp.status_code
        if resp.status_code != 200:
            record["ok"] = False
            print(f"[FAIL] {src['id']}: HTTP {resp.status_code}")
            return record

        out_path.write_bytes(resp.content)
        record["bytes"] = len(resp.content)
        record["sha256"] = hashlib.sha256(resp.content).hexdigest()
        record["ok"] = True
        print(f"[OK]   {src['id']}: {len(resp.content):,} bytes -> {out_path.name}")
    except Exception as exc:  # noqa: BLE001 - we want to record any failure
        record["ok"] = False
        record["error"] = f"{type(exc).__name__}: {exc}"
        print(f"[ERR]  {src['id']}: {record['error']}")
    return record


def main() -> None:
    SOURCES_DIR.mkdir(parents=True, exist_ok=True)
    manifest = [download_one(s) for s in SOURCES]

    manifest_path = SOURCES_DIR / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    ok = sum(1 for m in manifest if m.get("ok"))
    print(f"\nDownloaded {ok}/{len(manifest)} sources. Manifest: {manifest_path}")


if __name__ == "__main__":
    main()
