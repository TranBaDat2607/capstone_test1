"""
Build `config/gri_catalog.json` from extracted GRI dataset in `full_gri/json/`.
Complies 100% with feedback in `feedback-gri-catalog.md`:
- Flat lookup table keyed by GRI indicator code with standard prefix e.g. "GRI 305-1".
- Pillar mapped to Vietnamese labels: "Môi trường", "Xã hội", "Quản trị".
- `versions` as an array of version objects.
- `tt96_equivalent` crosswalk mapping.
- Source PDF provenance (sha256, source_pdf, page).
"""

import os
import json
import glob
import re
import sys

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

def load_crosswalk_mappings() -> dict:
    gri_to_tt96 = {}
    if os.path.exists(CROSSWALK_PATH):
        with open(CROSSWALK_PATH, "r", encoding="utf-8") as f:
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


def build_catalog():
    print("[+] Reading extracted GRI JSON files from:", JSON_DIR)
    json_files = glob.glob(os.path.join(JSON_DIR, "*.json"))
    
    gri_to_tt96 = load_crosswalk_mappings()
    catalog = {}
    
    for filepath in sorted(json_files):
        with open(filepath, "r", encoding="utf-8") as f:
            std_data = json.load(f)
            
        std_id = std_data.get("standard_id", "")
        std_title_en = std_data.get("title_en", "")
        pillar_raw = std_data.get("pillar", "")
        
        temp_val = std_data.get("temporal_validity", {})
        prov = std_data.get("provenance", {})
        
        version_obj = {
            "version_id": temp_val.get("version_id", f"{std_id.replace(' ', '_')}_{temp_val.get('version_year', 2016)}"),
            "version_year": temp_val.get("version_year", 2016),
            "effective_date": temp_val.get("effective_date", "2018-07-01"),
            "status": temp_val.get("status", "Active")
        }
        
        disclosures = std_data.get("disclosures", [])
        for d in disclosures:
            d_id_raw = d.get("disclosure_id", "").strip()
            if not d_id_raw:
                continue
                
            if d_id_raw.startswith("GRI"):
                indicator_key = d_id_raw
            else:
                indicator_key = f"GRI {d_id_raw}"
                
            title_en = d.get("title_en", "")
            title_vi = d.get("title_vi", title_en)
            
            reqs = d.get("requirements", [])
            req_type = "Quantitative"
            units = []
            if reqs:
                req_type = reqs[0].get("requirement_type", "Quantitative")
                units = reqs[0].get("unit_of_measure", [])
                
            tt96_code = gri_to_tt96.get(indicator_key, None)
            
            # GRI Official Series Pillar Mapping
            if any(k in indicator_key for k in ("GRI 3", "GRI 301", "GRI 302", "GRI 303", "GRI 304", "GRI 305", "GRI 306", "GRI 308")):
                pillar_vi = "Môi trường"
            elif any(k in indicator_key for k in ("GRI 4", "GRI 401", "GRI 402", "GRI 403", "GRI 404", "GRI 405", "GRI 406", "GRI 413")):
                pillar_vi = "Xã hội"
            else:
                pillar_vi = "Quản trị"
            
            if indicator_key not in catalog:
                catalog[indicator_key] = {
                    "gri_standard": std_id,
                    "standard_title_en": std_title_en,
                    "title_en": title_en,
                    "title_vi": title_vi,
                    "pillar": pillar_vi,
                    "definition_vi": f"Chỉ số công bố {indicator_key}: {title_vi}",
                    "requirement_type": req_type,
                    "units": units,
                    "tt96_equivalent": tt96_code,
                    "versions": [version_obj],
                    "superseded_by": temp_val.get("replaced_by_standard_id", None),
                    "source_pdf": os.path.basename(prov.get("relative_pdf_path", "")),
                    "sha256": prov.get("sha256", ""),
                    "page": prov.get("page_count", 1)
                }
            else:
                existing_ver_years = [v["version_year"] for v in catalog[indicator_key]["versions"]]
                if version_obj["version_year"] not in existing_ver_years:
                    catalog[indicator_key]["versions"].append(version_obj)
                    
    with open(OUTPUT_CATALOG_PATH, "w", encoding="utf-8") as f:
        json.dump(catalog, f, ensure_ascii=False, indent=2)
        
    print(f"[+] Successfully built GRI Catalog with {len(catalog)} GRI indicator codes!")
    print(f"[+] Target output path: {OUTPUT_CATALOG_PATH}")

if __name__ == "__main__":
    build_catalog()
