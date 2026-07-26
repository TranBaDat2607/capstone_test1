"""
Build `config/gri_catalog.json` from extracted GRI dataset in `full_gri/json/`.
Complies 100% with feedback in `feedback-gri-catalog.md`:
- Flat lookup table keyed by GRI indicator code with standard prefix e.g. "GRI 305-1".
- Pillar mapped to Vietnamese labels: "Môi trường", "Xã hội", "Quản trị".
- `versions` as an array of version objects.
- `tt96_equivalent` crosswalk mapping.
- Source PDF provenance (sha256, source_pdf, page).

Ownership rule (the thing that is easy to get wrong). A GRI standard's JSON does not
only describe its own disclosures: the sector standards (GRI 11-14) and the 2024/25
rewrites (GRI 101-103) re-list disclosures that belong to other standards. So a
disclosure is recorded from the standard whose `standard_id` is its prefix -- see
`standard_of()` -- not from whichever file happens to be read first. Before that rule
existed, `sorted(glob(...))` decided ownership and "gri_101" sorts before "gri_2", so
`GRI 2-27` was published with GRI 101 Biodiversity's title, PDF, sha256 and version.
80 of 136 entries were mis-attributed that way.

The pillar follows from the same decision, which is why the two are one concern: it is
a property of the STANDARD, read from the source via `PILLAR_MAP`, never guessed from
the shape of the indicator code.

Covered by `test/test_gri_catalog_build.py`.
"""

import os
import json
import glob
import sys
from typing import Any, Dict, Iterable, List, Optional

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(BASE_DIR)
JSON_DIR = os.path.join(BASE_DIR, "full_gri", "json")
CROSSWALK_PATH = os.path.join(REPO_ROOT, "config", "standard_crosswalk.json")
OUTPUT_CATALOG_PATH = os.path.join(REPO_ROOT, "config", "gri_catalog.json")

PILLAR_MAP = {
    "E — Environmental": "Môi trường",
    "S — Social": "Xã hội",
    "G — Governance": "Quản trị",
    "Universal": "Quản trị",
    "Sector": "Môi trường"
}


def standard_of(indicator_key: str, known_standard_ids: Iterable[str]) -> Optional[str]:
    """"GRI 2-27" -> "GRI 2": the standard that OWNS this disclosure.

    Returns None when no such standard was extracted, which the caller treats as
    "keep the first sighting" rather than dropping the disclosure.
    """
    base = indicator_key.rsplit("-", 1)[0].strip()
    return base if base in set(known_standard_ids) else None


def load_crosswalk_mappings(crosswalk_path: str = CROSSWALK_PATH) -> dict:
    gri_to_tt96 = {}
    if os.path.exists(crosswalk_path):
        with open(crosswalk_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            for section in ["confirmed", "needs_review"]:
                for row in data.get(section, []):
                    tt96_code = row.get("tt96")
                    gri_codes = row.get("gri", [])
                    for g_code in gri_codes:
                        clean_g = g_code.strip()
                        if clean_g and clean_g not in gri_to_tt96:
                            gri_to_tt96[clean_g] = tt96_code
    return gri_to_tt96


def _indicator_key(disclosure: Dict[str, Any]) -> Optional[str]:
    raw = (disclosure.get("disclosure_id") or "").strip()
    if not raw:
        return None
    return raw if raw.startswith("GRI") else f"GRI {raw}"


def _version_of(std_data: Dict[str, Any]) -> Dict[str, Any]:
    tv = std_data.get("temporal_validity", {}) or {}
    sid = (std_data.get("standard_id") or "").strip()
    return {
        "version_id": tv.get("version_id", f"{sid.replace(' ', '_')}_{tv.get('version_year', 2016)}"),
        "version_year": tv.get("version_year", 2016),
        "effective_date": tv.get("effective_date", "2018-07-01"),
        "status": tv.get("status", "Active"),
    }


def _versions_of(docs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """All versions of ONE standard (GRI 306 really does ship as 2016 and 2020)."""
    out: List[Dict[str, Any]] = []
    seen = set()
    for std_data in docs:
        v = _version_of(std_data)
        if v["version_year"] not in seen:
            seen.add(v["version_year"])
            out.append(v)
    return out


def _pillar_of(std_data: Dict[str, Any]) -> str:
    raw = std_data.get("pillar", "")
    mapped = PILLAR_MAP.get(raw)
    if mapped is None:
        print(f"[!] Unknown pillar {raw!r} on {std_data.get('standard_id')!r}; defaulting to Quản trị")
        return "Quản trị"
    return mapped


def _entry(indicator_key: str, disclosure: Dict[str, Any], std_data: Dict[str, Any],
           versions: List[Dict[str, Any]], tt96_code: Optional[str]) -> Dict[str, Any]:
    prov = std_data.get("provenance", {}) or {}
    tv = std_data.get("temporal_validity", {}) or {}
    title_en = disclosure.get("title_en", "")
    title_vi = disclosure.get("title_vi", title_en)
    reqs = disclosure.get("requirements", []) or []
    req_type = reqs[0].get("requirement_type", "Quantitative") if reqs else "Quantitative"
    units = reqs[0].get("unit_of_measure", []) if reqs else []
    return {
        "gri_standard": (std_data.get("standard_id") or "").strip(),
        "standard_title_en": std_data.get("title_en", ""),
        "title_en": title_en,
        "title_vi": title_vi,
        "pillar": _pillar_of(std_data),
        "definition_vi": f"Chỉ số công bố {indicator_key}: {title_vi}",
        "requirement_type": req_type,
        "units": units,
        "tt96_equivalent": tt96_code,
        "versions": versions,
        "superseded_by": tv.get("replaced_by_standard_id", None),
        "source_pdf": os.path.basename(prov.get("relative_pdf_path", "")),
        "sha256": prov.get("sha256", ""),
        "page": prov.get("page_count", 1),
    }


def build_catalog(json_dir: str = JSON_DIR,
                  crosswalk_path: str = CROSSWALK_PATH,
                  out_path: str = OUTPUT_CATALOG_PATH) -> Dict[str, Any]:
    print("[+] Reading extracted GRI JSON files from:", json_dir)
    json_files = sorted(glob.glob(os.path.join(str(json_dir), "*.json")))

    gri_to_tt96 = load_crosswalk_mappings(crosswalk_path)

    # Pass 1 - index every extracted standard. One standard_id can appear in several
    # files because it ships several versions, so keep them all, in filename order.
    docs_in_order: List[Dict[str, Any]] = []
    by_standard: Dict[str, List[Dict[str, Any]]] = {}
    for filepath in json_files:
        with open(filepath, "r", encoding="utf-8") as f:
            std_data = json.load(f)
        docs_in_order.append(std_data)
        sid = (std_data.get("standard_id") or "").strip()
        if sid:
            by_standard.setdefault(sid, []).append(std_data)

    known = set(by_standard)
    catalog: Dict[str, Any] = {}

    # Pass 2 - a standard describes only the disclosures it owns. A foreign listing
    # (GRI 11 re-stating GRI 404-1) is skipped so it cannot claim the provenance.
    for std_data in docs_in_order:
        sid = (std_data.get("standard_id") or "").strip()
        for d in std_data.get("disclosures", []):
            key = _indicator_key(d)
            if not key or key in catalog or standard_of(key, known) != sid:
                continue
            catalog[key] = _entry(key, d, std_data, _versions_of(by_standard[sid]),
                                  gri_to_tt96.get(key))

    # Pass 3 - orphans: nothing extracted declares the owning standard, so the first
    # sighting stands. Better a disclosure with approximate provenance than none.
    for std_data in docs_in_order:
        sid = (std_data.get("standard_id") or "").strip()
        for d in std_data.get("disclosures", []):
            key = _indicator_key(d)
            if not key or key in catalog:
                continue
            catalog[key] = _entry(key, d, std_data, _versions_of(by_standard.get(sid, [std_data])),
                                  gri_to_tt96.get(key))

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(catalog, f, ensure_ascii=False, indent=2)

    print(f"[+] Successfully built GRI Catalog with {len(catalog)} GRI indicator codes!")
    print(f"[+] Target output path: {out_path}")
    return catalog


if __name__ == "__main__":
    build_catalog()
