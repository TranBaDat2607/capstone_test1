#!/usr/bin/env python3
"""
Stage 4 - Extract sector-specific KPI content from the three sector sources
downloaded in Stage 3 (+ the SSC-IFC guide from Stage 1):

  * QD 2171/QD-TTg  -> non-fired building-materials usage target  (Building Materials)
  * QCVN 09:2017/BXD -> energy-efficient building compliance       (Construction / Real Estate)
  * SSC-IFC guide    -> 14 recommended E&S aspects (waste, biodiversity, OHS, ...)

All text is taken verbatim from the documents. Vietnamese is normalised to NFC
(some legal portals serve NFD combining diacritics).

Output: sources/extracted_sector.json

Run:
    python 04_extract_sector_kpis.py
"""

import json
import pathlib
import re
import unicodedata

import fitz
from bs4 import BeautifulSoup

HERE = pathlib.Path(__file__).resolve().parent
SRC = HERE / "sources"


def html_text(name: str) -> str:
    t = BeautifulSoup((SRC / name).read_bytes(), "html.parser").get_text("\n")
    return unicodedata.normalize("NFC", t)


def pdf_text(name: str) -> str:
    return unicodedata.normalize("NFC", "\n".join(p.get_text() for p in fitz.open(SRC / name)))


def squash(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip(" .;:")


# --------------------------------------------------------------------------- #
def extract_qd2171() -> list[dict]:
    text = html_text("QD_2171_2021.html")
    doc = {
        "document": "Quyết định 2171/QĐ-TTg (23/12/2021) - Chương trình phát triển "
                    "vật liệu xây không nung tại Việt Nam đến năm 2030",
        "url": "https://hethongphapluat.com/quyet-dinh-2171-qd-ttg-nam-2021-phe-duyet-chuong-trinh-phat-trien-vat-lieu-xay-khong-nung-tai-viet-nam-den-nam-2030-do-thu-tuong-chinh-phu-ban-hanh/dieu-1",
        "section": "Điều 1.b - Mục tiêu cụ thể",
    }
    # Specific-target sentence (under "b) Mục tiêu cụ thể"):
    # "... đạt tỷ lệ: 35 - 40% vào năm 2025, 40 - 45% vào năm 2030 ... theo quy định"
    m = re.search(r"(Đẩy mạnh sản xuất và sử dụng vật liệu xây không nung thay thế "
                  r"một phần gạch đất sét nung đạt tỷ lệ:.*?theo quy định)",
                  text, flags=re.S)
    if not m:
        raise SystemExit("QD2171: could not locate the non-fired materials target.")
    return [{
        "source_id": "QD2171-1",
        "pillar": "Môi trường",
        "name": "Tỷ lệ sử dụng vật liệu xây không nung (VLXKN)",
        "vi": squash(m.group(1)),
        "source": doc,
    }]


# --------------------------------------------------------------------------- #
def extract_qcvn09() -> list[dict]:
    text = html_text("QCVN_09_2017.html")
    doc = {
        "document": "QCVN 09:2017/BXD - Quy chuẩn kỹ thuật quốc gia về các công trình "
                    "xây dựng sử dụng năng lượng hiệu quả",
        "url": "https://hethongphapluat.com/quy-chuan-ky-thuat-quoc-gia-qcvn-09-2017-bxd-ve-cac-cong-trinh-xay-dung-su-dung-nang-luong-hieu-qua.html",
        "section": "Mục 1.1 - Phạm vi điều chỉnh",
    }
    m = re.search(r"(Quy chuẩn kỹ thuật quốc gia về các công trình xây dựng sử dụng "
                  r"năng lượng hiệu quả quy định.*?trở lên)", text, flags=re.S)
    if not m:
        raise SystemExit("QCVN09: could not locate the scope sentence.")
    return [{
        "source_id": "QCVN09-1",
        "pillar": "Môi trường",
        "name": "Tuân thủ quy chuẩn công trình sử dụng năng lượng hiệu quả (QCVN 09:2017/BXD)",
        "vi": squash(m.group(1)),
        "source": doc,
    }]


# --------------------------------------------------------------------------- #
def extract_ssc_ifc_aspects() -> list[dict]:
    guide = pdf_text("SSC_IFC_sustainability_guide.pdf")
    doc = {
        "document": "Hướng dẫn lập Báo cáo Phát triển bền vững (SSC - IFC)",
        "url": "https://ssc.gov.vn/ (SSC IFC Huong dan lap Bao cao Phat trien ben vung.pdf)",
        "section": "Mục 5 - Khía cạnh hoạt động kinh doanh được đề cập trong Báo cáo bền vững",
    }
    # The aspect list is a two-column table (Moi truong | Xa hoi) rendered as
    # alternating lines between the "Moi truong / Xa hoi" header and the next paragraph.
    start = guide.find("Tiết kiệm năng lượng")
    end = guide.find("Thông tin được công bố", start)
    if start < 0 or end < 0:
        raise SystemExit("SSC-IFC: could not locate the aspect list.")
    lines = [ln.strip() for ln in guide[start:end].splitlines() if ln.strip()]
    lines = [ln for ln in lines if ln not in ("Môi trường", "Xã hội")]
    env, soc = lines[0::2], lines[1::2]  # alternating E, S

    items = []
    for i, vi in enumerate(env, 1):
        items.append({"source_id": f"SSCIFC-E{i}", "pillar": "Môi trường",
                      "name": vi, "vi": vi, "source": doc})
    for i, vi in enumerate(soc, 1):
        items.append({"source_id": f"SSCIFC-S{i}", "pillar": "Xã hội",
                      "name": vi, "vi": vi, "source": doc})
    return items


def main() -> None:
    items = extract_qd2171() + extract_qcvn09() + extract_ssc_ifc_aspects()
    (SRC / "extracted_sector.json").write_text(
        json.dumps({"n_items": len(items), "items": items}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Extracted {len(items)} sector indicators:\n")
    for it in items:
        print(f"  [{it['source_id']:>10}] ({it['pillar']}) {it['vi'][:80]}")
    print(f"\nWrote: {SRC / 'extracted_sector.json'}")


if __name__ == "__main__":
    main()
