#!/usr/bin/env python3
"""
Stage 5 - Build the final kpi_definitions_construction.json by merging:
    * Stage 2 output: Circular 96/2020 Section 6 indicators (regulatory backbone)
    * Stage 4 output: sector-specific indicators (QD 2171, QCVN 09, SSC-IFC guide)

Every KPI is derived from a source document and carries a `source` block. Schema
per record: id, name, definition, sector, pillar, source.

Run:
    python 05_build_kpi_definitions.py
"""

import json
import pathlib

HERE = pathlib.Path(__file__).resolve().parent
SRC = HERE / "sources"
OUT = HERE.parent / "kpi_definitions_construction.json"

SECTOR_LABEL = "Xây dựng - Vật liệu xây dựng - Bất động sản"

# Targeted fixes for OCR/source artefacts found in the original document text.
TEXT_FIXES = {"Chính sách lao độngnhằm": "Chính sách lao động nhằm"}

PILLAR_BY_SUBSECTION = {
    "6.1": "Môi trường", "6.2": "Môi trường", "6.3": "Môi trường",
    "6.4": "Môi trường", "6.5": "Môi trường",
    "6.6": "Xã hội", "6.7": "Xã hội", "6.8": "Quản trị",
}


def fix(text: str) -> str:
    for bad, good in TEXT_FIXES.items():
        text = text.replace(bad, good)
    return text.strip()


def short_name(vi: str) -> str:
    for prefix in ("Báo cáo liên quan đến ", "Báo cáo "):
        if vi.startswith(prefix):
            vi = vi[len(prefix):]
            return vi[0].upper() + vi[1:]
    return vi


def build_circular96() -> list[dict]:
    data = json.loads((SRC / "extracted_section6.json").read_text("utf-8"))
    sdoc = data["source"]
    out = []
    for it in data["items"]:
        sub = it["subsection"]
        vi = fix(it["vi"])
        out.append({
            "id": f"TT96-{sub}.{it['index_in_subsection']}",
            "name": short_name(vi),
            "definition": vi,
            "sector": [SECTOR_LABEL],
            "pillar": PILLAR_BY_SUBSECTION.get(sub, ""),
            "source": {
                "document": sdoc["document"],
                "section": f"Mục {sub} - {it['subsection_title']}",
                "url": sdoc["url"],
            },
        })
    return out


def build_sector() -> list[dict]:
    data = json.loads((SRC / "extracted_sector.json").read_text("utf-8"))
    out = []
    for it in data["items"]:
        vi = fix(it["vi"])
        out.append({
            "id": it["source_id"],
            "name": it["name"],
            "definition": vi,
            "sector": [SECTOR_LABEL],
            "pillar": it["pillar"],
            "source": {
                "document": it["source"]["document"],
                "section": it["source"]["section"],
                "url": it["source"]["url"],
            },
        })
    return out


def main() -> None:
    kpis = build_circular96() + build_sector()

    # Sanity: ids must stay unique (pipeline uses id as kpi_type token).
    ids = [k["id"] for k in kpis]
    assert len(ids) == len(set(ids)), "duplicate KPI ids!"

    OUT.write_text(json.dumps(kpis, ensure_ascii=False, indent=2), encoding="utf-8")

    by_pillar, by_doc = {}, {}
    for k in kpis:
        by_pillar[k["pillar"]] = by_pillar.get(k["pillar"], 0) + 1
        doc = k["source"]["document"].split(" - ")[0]
        by_doc[doc] = by_doc.get(doc, 0) + 1
    print(f"Wrote {len(kpis)} KPIs -> {OUT}\n")
    print("By pillar:", by_pillar)
    print("By source:")
    for d, n in by_doc.items():
        print(f"   {n:>2}  {d}")


if __name__ == "__main__":
    main()
