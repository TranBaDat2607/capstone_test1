#!/usr/bin/env python3
"""
Stage 2 - Extract Section 6 ("Bao cao tac dong lien quan den moi truong va xa
hoi" / ESG Report) from the downloaded Circular 96/2020/TT-BTC Annex IV template.

The Circular's annual-report template lists, sub-section by sub-section, exactly
which environmental & social indicators a listed company must disclose. We slice
that section out and parse every mandated indicator into a structured item.

The template is bilingual: each indicator reads "<Vietnamese>/<English>" and the
two languages are interleaved on one line after whitespace normalisation. We rely
on the fact that Vietnamese words carry tone marks / special letters that the
English translation does not, to cut the Vietnamese indicator out of each unit.

Output: sources/extracted_section6.json  +  sources/extracted_section6.txt

Run:
    python 02_extract_section6.py
"""

import json
import pathlib
import re

from bs4 import BeautifulSoup

HERE = pathlib.Path(__file__).resolve().parent
SRC = HERE / "sources"

SOURCE_DOC = {
    "document": "Thong tu 96/2020/TT-BTC - Phu luc IV (Mau Bao cao thuong nien), "
                "Muc 6: Bao cao tac dong lien quan den moi truong va xa hoi",
    "url": "https://luatminhkhue.vn/mau-bao-cao-thuong-nien-ban-hanh-theo-thong-tu-so-96-2020-tt-btc.aspx",
    "file": "TT96_2020_phuluc4.html",
}

SUBSECTION_TITLES = {
    "6.1": "Tác động lên môi trường (phát thải khí nhà kính)",
    "6.2": "Quản lý nguồn nguyên vật liệu",
    "6.3": "Tiêu thụ năng lượng",
    "6.4": "Tiêu thụ nước",
    "6.5": "Tuân thủ pháp luật về bảo vệ môi trường",
    "6.6": "Chính sách liên quan đến người lao động",
    "6.7": "Trách nhiệm đối với cộng đồng địa phương",
    "6.8": "Hoạt động thị trường vốn xanh",
}

# Vietnamese-specific letters (lowercase + uppercase). A token that contains any
# of these is treated as Vietnamese rather than part of the English translation.
VI_CHARS = set(
    "ăâđêôơưĂÂĐÊÔƠƯ"
    "áàảãạấầẩẫậắằẳẵặéèẻẽẹếềểễệíìỉĩịóòỏõọốồổỗộớờởỡợúùủũụứừửữựýỳỷỹỵ"
    "ÁÀẢÃẠẤẦẨẪẬẮẰẲẴẶÉÈẺẼẸẾỀỂỄỆÍÌỈĨỊÓÒỎÕỌỐỒỔỖỘỚỜỞỠỢÚÙỦŨỤỨỪỬỮỰÝỲỶỸỴ"
)


def is_vietnamese(token: str) -> bool:
    return any(ch in VI_CHARS for ch in token)


def html_to_text(path: pathlib.Path) -> str:
    return BeautifulSoup(path.read_bytes(), "html.parser").get_text("\n")


def slice_section6(text: str) -> str:
    """Return the raw text of Section 6 only (up to the 'Luu y/Note' after 6.8)."""
    start = text.lower().find("báo cáo tác động liên quan đến môi trường và xã hội")
    if start < 0:
        raise SystemExit("Could not locate Section 6 in the template HTML.")
    tail = text[start:]
    # Section 6 closes with the "Luu y/Note:" paragraph that follows item 6.8.
    end_match = re.search(r"L[ưu]+\s*ý\s*/\s*Note", tail)
    if not end_match:
        end_match = re.search(r"\n\s*III\.\s", tail)  # fallback: next Roman part
    end = end_match.start() if end_match else min(len(tail), 5000)
    return tail[:end]


def normalize(block: str) -> str:
    one = re.sub(r"\s+", " ", block).strip()
    one = re.sub(r"6\.\s*(\d)\s*\.", r"6.\1.", one)  # rejoin "6. 3 ." -> "6.3."
    return one


def vi_tail(piece: str) -> str:
    """Given an 'English... Vietnamese...' fragment, return the Vietnamese tail."""
    words = piece.split()
    for i, w in enumerate(words):
        if is_vietnamese(w):
            return " ".join(words[i:])
    return ""


def clean(seg: str) -> str:
    seg = re.sub(r"^[a-eA-E]\)\s*", "", seg.strip())   # drop "a) " markers
    seg = seg.strip(" .;:- ")
    return re.sub(r"\s+", " ", seg)


def vi_indicators(body: str) -> list[str]:
    """Split a bilingual body into its Vietnamese indicator phrases."""
    pieces = body.split("/")
    out: list[str] = []
    for i, piece in enumerate(pieces):
        if i == 0:
            cand = piece                       # text before first slash = VN
        elif i == len(pieces) - 1:
            continue                           # trailing English after last slash
        else:
            cand = vi_tail(piece)              # 'EN_prev VN_next' -> VN_next
        cand = clean(cand)
        if len(cand) >= 5 and is_vietnamese(cand) and not cand.startswith("("):
            out.append(cand)
    return out


def parse_section6(block: str) -> list[dict]:
    one = normalize(block)
    headers = list(re.finditer(r"6\.(\d)\.", one))
    items: list[dict] = []
    for idx, h in enumerate(headers):
        code = f"6.{h.group(1)}"
        seg = one[h.end(): headers[idx + 1].start() if idx + 1 < len(headers) else len(one)]

        # Strip the sub-section title: cut at the first "a)" if items are lettered,
        # else at the first ":" (title delimiter), else keep the whole segment.
        m_letter = re.search(r"\sa\)\s", seg)
        if m_letter:
            body = seg[m_letter.start():]
        elif ":" in seg[:120]:
            body = seg.split(":", 1)[1]
        else:
            body = seg

        for pos, vi in enumerate(vi_indicators(body), start=1):
            items.append({
                "subsection": code,
                "subsection_title": SUBSECTION_TITLES.get(code, ""),
                "index_in_subsection": pos,
                "vi": vi,
            })
    return items


def main() -> None:
    text = html_to_text(SRC / "TT96_2020_phuluc4.html")
    block = slice_section6(text)
    (SRC / "extracted_section6.txt").write_text(block, encoding="utf-8")

    items = parse_section6(block)
    out = {"source": SOURCE_DOC, "n_items": len(items), "items": items}
    (SRC / "extracted_section6.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"Extracted {len(items)} mandated indicators from Section 6:\n")
    for it in items:
        print(f"  [{it['subsection']}.{it['index_in_subsection']}] {it['vi']}")
    print(f"\nWrote: {SRC / 'extracted_section6.json'}")


if __name__ == "__main__":
    main()
