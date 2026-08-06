"""
GRI Standards Full Data Extractor & Indexer (Temporal KG Aligned - Datalab API Powered)
Quản lý, đánh chỉ mục và chuyển đổi 42 tài liệu PDF GRI Standards thành dữ liệu cấu trúc JSON chuẩn enterprise
sử dụng Datalab API Key và tuân thủ 100% Nguyên tắc thiết kế Temporal Knowledge Graph (TEMPORAL_KG_DESIGN.md).
"""

import os
import sys

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FULL_GRI_DIR = os.path.join(BASE_DIR, "full_gri")

# Import conversion & parsing modules
sys.path.insert(0, BASE_DIR)
sys.path.insert(0, FULL_GRI_DIR)

from full_gri.convert_pdf_to_markdown import convert_all_gri_pdfs
from full_gri.parse_gri_markdown import parse_and_generate_all_json


def run_full_pipeline():
    """Khởi chạy toàn bộ pipeline: Convert Datalab PDF -> Markdown -> Parse Schema -> Master Catalog"""
    print("=========================================================================")
    print("[+] KHOI CHAY ENTERPRISE GRI EXTRACTION PIPELINE VIA DATALAB API")
    print("=========================================================================")
    
    # Step 1: Datalab Conversion
    convert_all_gri_pdfs()
    
    # Step 2: High-precision Markdown Parser & JSON Generator
    parse_and_generate_all_json()
    
    print("\n=========================================================================")
    print("[✔] PIPELINE ENTERPRISE DA HOAN THANH THANH CONG 100%!")
    print("=========================================================================")


if __name__ == "__main__":
    run_full_pipeline()
