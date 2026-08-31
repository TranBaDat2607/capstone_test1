"""
GRI Standards Full Data Extractor & Indexer (Temporal KG Aligned)
Quản lý, đánh chỉ mục và chuyển đổi 42 tài liệu PDF GRI Standards trong folder
'gri/full_gri/Full set of GRI Standards - English' thành dữ liệu cấu trúc JSON chuẩn enterprise,
tuân thủ 100% Nguyên tắc thiết kế Temporal Knowledge Graph (TEMPORAL_KG_DESIGN.md).
"""

import os
import json
import re
import glob
import hashlib
import sys
from datetime import datetime
from typing import Dict, List, Any, Optional

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')

try:
    import fitz
except ImportError:
    fitz = None

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FULL_GRI_DIR = os.path.join(BASE_DIR, "full_gri")
PDF_DIR = os.path.join(FULL_GRI_DIR, "Full set of GRI Standards - English")
JSON_DIR = os.path.join(FULL_GRI_DIR, "json")
MANIFEST_FILE = os.path.join(FULL_GRI_DIR, "manifest.json")
SUMMARY_FILE = os.path.join(BASE_DIR, "gri_standards_summary.json")

os.makedirs(JSON_DIR, exist_ok=True)


def calculate_file_sha256(filepath: str) -> str:
    """Tính mã SHA256 cho file PDF"""
    sha256_hash = hashlib.sha256()
    with open(filepath, "rb") as f:
        for byte_block in iter(lambda: f.read(65536), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()


def parse_filename_metadata(filename: str) -> Dict[str, Any]:
    """Trích xuất thông tin metadata từ tên file PDF của GRI"""
    name_no_ext = os.path.splitext(filename)[0]
    
    if "Glossary" in name_no_ext:
        return {
            "standard_id": "GRI Glossary",
            "title_en": "GRI Standards Glossary 2025",
            "title_vi": "Thuật ngữ và Định nghĩa GRI 2025",
            "version_year": 2025,
            "pillar": "Universal",
            "series": "Glossary",
            "category": "Reference"
        }
        
    match = re.match(r"^(GRI\s*\d+)[_\s]+(.*)$", name_no_ext, re.IGNORECASE)
    if match:
        std_id = match.group(1).upper()
        std_id = re.sub(r"GRI\s*0+", "GRI ", std_id)
        rest = match.group(2).strip()
        
        year_match = re.search(r"\b(20[12]\d)\b", rest)
        version_year = int(year_match.group(1)) if year_match else 2016
        
        number_part = re.sub(r"\D", "", std_id)
        num = int(number_part) if number_part else 0
        
        if num in [1, 2, 3]:
            pillar = "Universal"
            series = "Universal Standards"
            category = "Universal"
        elif 11 <= num <= 99:
            pillar = "Sector"
            series = f"Sector Standards (GRI {num})"
            category = "Sector"
        elif 200 <= num <= 299:
            pillar = "G — Governance"
            series = "Economic (200 Series)"
            category = "Topic-Economic"
        elif 300 <= num <= 399 or num == 101 or num == 102 or num == 103:
            pillar = "E — Environmental"
            series = "Environmental (300 Series / Revisions)"
            category = "Topic-Environmental"
        elif 400 <= num <= 499:
            pillar = "S — Social"
            series = "Social (400 Series)"
            category = "Topic-Social"
        else:
            pillar = "Universal"
            series = "General"
            category = "General"
            
        clean_title = re.sub(r"\s*-\s*English$", "", rest, flags=re.IGNORECASE).strip()
        
        return {
            "standard_id": std_id,
            "title_en": clean_title,
            "title_vi": clean_title,
            "version_year": version_year,
            "pillar": pillar,
            "series": series,
            "category": category
        }
        
    return {
        "standard_id": name_no_ext,
        "title_en": name_no_ext,
        "title_vi": name_no_ext,
        "version_year": 2021,
        "pillar": "Universal",
        "series": "General",
        "category": "General"
    }


def extract_disclosures_from_pdf(filepath: str, std_id: str) -> List[Dict[str, Any]]:
    """Phân tích nội dung text của PDF để tìm các chỉ số Disclosure và Requirements"""
    disclosures = []
    if not fitz:
        return disclosures
        
    try:
        doc = fitz.open(filepath)
        full_text = ""
        for page in doc:
            full_text += page.get_text() + "\n"
            
        pattern = r"(Disclosure\s+(\d+[\-\.]\d+)\s+([^\n\r]+))"
        matches = re.findall(pattern, full_text)
        
        seen_ids = set()
        for full_match, d_code, d_title in matches:
            d_code_clean = d_code.strip()
            if d_code_clean not in seen_ids:
                seen_ids.add(d_code_clean)
                req_id = f"{d_code_clean}:a"
                disclosures.append({
                    "disclosure_id": d_code_clean,
                    "title_en": d_title.strip(),
                    "title_vi": d_title.strip(),
                    "disclosure_type": "Topic-Specific" if "2" not in std_id and "3" not in std_id else "General Disclosures",
                    "mandatory": True,
                    "requirements": [
                        {
                            "requirement_id": req_id,
                            "item_code": "a",
                            "description_en": f"Report according to requirement of {d_code_clean} ({d_title.strip()})",
                            "description_vi": None,
                            "requirement_type": "Quantitative" if any(k in d_title.lower() for k in ["emission", "energy", "water", "waste", "tax", "payment", "number"]) else "Qualitative",
                            "unit_of_measure": ["metric tons CO2e"] if "305" in std_id else [],
                            "breakdown_dimensions": ["by Scope", "by facility"] if "305" in std_id else []
                        }
                    ],
                    "recommendations_en": None,
                    "recommendations_vi": None,
                    "sdg_mapping": [],
                    "esrs_mapping": [],
                    "issb_mapping": []
                })
    except Exception as e:
        print(f"[-] Lỗi khi trích xuất PDF {filepath}: {e}")
        
    return disclosures


def index_all_downloaded_gri_files():
    """Hàm xử lý chính: Đánh chỉ mục 42 file PDF GRI và xây dựng Master JSON Manifest"""
    print("=========================================================================")
    print("[+] DANG KHOI CHAY TIEN TRINH XU LY & DANH CHI MUC TOAN BO DU LIEU GRI")
    print("=========================================================================")
    
    if not os.path.exists(PDF_DIR):
        print(f"[-] Thu muc {PDF_DIR} khong ton tai.")
        return

    pdf_files = glob.glob(os.path.join(PDF_DIR, "*.pdf"))
    print(f"[+] Tim thay tong cong {len(pdf_files)} file PDF GRI trong folder full_gri.")
    
    manifest_entries = []
    total_disclosures = 0
    
    for pdf_path in sorted(pdf_files):
        filename = os.path.basename(pdf_path)
        file_size = os.path.getsize(pdf_path)
        checksum = calculate_file_sha256(pdf_path)
        
        meta = parse_filename_metadata(filename)
        std_id = meta["standard_id"]
        
        page_count = 0
        if fitz:
            try:
                doc = fitz.open(pdf_path)
                page_count = len(doc)
            except Exception:
                pass
                
        extracted_disclosures = extract_disclosures_from_pdf(pdf_path, std_id)
        
        status = "Active"
        replaced_by = None
        if "304" in std_id:
            status = "Superseded"
            replaced_by = "GRI 101"
        elif "306_ Effluents" in filename:
            status = "Superseded"
            replaced_by = "GRI 306 & GRI 303"
            
        version_id = f"{re.sub(r'[^a-zA-Z0-9_]', '_', std_id)}_{meta['version_year']}"
        
        record = {
            "node_tier": "T1 — Identity (Thực thể bền phi thời gian)",
            "standard_id": std_id,
            "title_en": meta["title_en"],
            "title_vi": meta["title_vi"],
            "pillar": meta["pillar"],
            "series": meta["series"],
            "category": meta["category"],
            "temporal_validity": {
                "version_id": version_id,
                "version_year": meta["version_year"],
                "effective_date": f"{meta['version_year']+1}-01-01",
                "valid_until_year": None if status == "Active" else 2023,
                "status": status,
                "replaced_by_standard_id": replaced_by
            },
            "scope": {
                "target_audience": "Tất cả tổ chức" if meta["pillar"] == "Universal" else f"Tổ chức thuộc nhóm {meta['series']}",
                "sector_code": std_id if meta["category"] == "Sector" else None,
                "materiality_required": False if meta["pillar"] == "Universal" else True,
                "boundary_scope": "Toàn bộ tổ chức & Chuỗi giá trị"
            },
            "provenance": {
                "relative_pdf_path": os.path.join("Full set of GRI Standards - English", filename),
                "file_size_bytes": file_size,
                "page_count": page_count,
                "sha256": checksum,
                "indexed_at": datetime.now().isoformat()
            },
            "disclosures_count": len(extracted_disclosures),
            "disclosures": extracted_disclosures
        }
        
        json_filename = f"{re.sub(r'[^a-zA-Z0-9_]', '_', std_id).lower()}_{meta['version_year']}.json"
        target_json_path = os.path.join(JSON_DIR, json_filename)
        
        with open(target_json_path, "w", encoding="utf-8") as f:
            json.dump(record, f, ensure_ascii=False, indent=2)
            
        total_disclosures += len(extracted_disclosures)
        
        manifest_entries.append({
            "standard_id": std_id,
            "filename": filename,
            "title_en": meta["title_en"],
            "version_year": meta["version_year"],
            "pillar": meta["pillar"],
            "category": meta["category"],
            "status": status,
            "replaced_by": replaced_by,
            "page_count": page_count,
            "file_size_bytes": file_size,
            "disclosures_count": len(extracted_disclosures),
            "json_path": os.path.join("json", json_filename),
            "sha256": checksum
        })
        
        print(f"  [+] Da ma hoa & danh chi muc: {std_id:<12} | {meta['title_en'][:40]:<40} | {page_count:>3} trang | {file_size/1024:.1f} KB")

    manifest_data = {
        "system": "GRI Standards Enterprise Master Catalog",
        "version": "2026.1",
        "temporal_kg_design_alignment": "TEMPORAL_KG_DESIGN.md (3-Tier Node Model & P1-P8 Principles)",
        "total_files": len(manifest_entries),
        "total_disclosures_extracted": total_disclosures,
        "updated_at": datetime.now().isoformat(),
        "schema_reference": "gri_schema.json",
        "standards": manifest_entries
    }
    
    with open(MANIFEST_FILE, "w", encoding="utf-8") as f:
        json.dump(manifest_data, f, ensure_ascii=False, indent=2)
        
    print("\n=========================================================================")
    print(f"[✔] HOAN THANH DANH CHI MUC MASTER CATALOG GOM {len(manifest_entries)} TIEU CHUAN GRI!")
    print(f"    Manifest catalog: {MANIFEST_FILE}")
    print(f"    Thu muc JSON: {JSON_DIR}")
    print("=========================================================================")


if __name__ == "__main__":
    index_all_downloaded_gri_files()
