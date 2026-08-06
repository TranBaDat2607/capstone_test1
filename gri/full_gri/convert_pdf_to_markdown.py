"""
Datalab PDF to Markdown Batch Converter & Cache Manager with Rate Limit (429) Retry
Tải và lưu vết cache kết quả Markdown của 42 file PDF GRI từ Datalab API.
Tự động chờ 12s nếu gặp lỗi HTTP 429 Rate Limit (25 requests / 60 seconds).
"""

import os
import glob
import time
import requests
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PDF_DIR = os.path.join(BASE_DIR, "Full set of GRI Standards - English")
CACHE_DIR = os.path.join(BASE_DIR, "markdown_cache")
ENV_FILE = os.path.abspath(os.path.join(BASE_DIR, "..", "..", ".env"))

os.makedirs(CACHE_DIR, exist_ok=True)


def get_datalab_api_key() -> str:
    """Lấy API Key Datalab từ file .env"""
    if os.path.exists(ENV_FILE):
        with open(ENV_FILE, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip().startswith("datalab"):
                    parts = line.split("=", 1)
                    if len(parts) == 2:
                        return parts[1].strip().strip('"').strip("'")
    raise ValueError(f"Không tìm thấy Datalab API Key trong {ENV_FILE}")


def convert_pdf_to_markdown(pdf_path: str, api_key: str) -> str:
    """
    Gửi PDF tới Datalab Marker API và trả về chuỗi Markdown.
    Tự động retry nếu gặp lỗi 429 Rate Limit.
    """
    filename = os.path.basename(pdf_path)
    cache_path = os.path.join(CACHE_DIR, f"{filename}.md")

    if os.path.exists(cache_path) and os.path.getsize(cache_path) > 100:
        with open(cache_path, "r", encoding="utf-8") as f:
            return f.read()

    url = "https://www.datalab.to/api/v1/marker"
    headers = {"X-Api-Key": api_key}

    max_post_retries = 5
    resp = None
    for attempt in range(max_post_retries):
        print(f"  [➔] Đang gửi Datalab API cho PDF: {filename} (Thử {attempt+1}/{max_post_retries})...")
        with open(pdf_path, "rb") as f:
            resp = requests.post(
                url,
                files={"file": (filename, f, "application/pdf")},
                headers=headers
            )
        if resp.status_code == 429:
            print(f"  [!] HTTP 429 Rate Limit cho {filename}. Chờ 12s trước khi thử lại...")
            time.sleep(12)
            continue
        elif resp.status_code == 200:
            break
        else:
            raise RuntimeError(f"Lỗi API Datalab HTTP {resp.status_code}: {resp.text}")

    if not resp or resp.status_code != 200:
        raise RuntimeError(f"Lỗi API Datalab sau nhiều lần thử: {resp.text if resp else 'No response'}")

    data = resp.json()
    if not data.get("success", False):
        raise RuntimeError(f"Lỗi khởi tạo job Datalab: {data}")

    check_url = data["request_check_url"]

    # Poll status
    max_poll_retries = 60
    for attempt in range(max_poll_retries):
        time.sleep(3)
        res = requests.get(check_url, headers=headers)
        if res.status_code == 429:
            time.sleep(10)
            continue
            
        res_data = res.json()
        status = res_data.get("status")

        if status == "complete":
            md_content = res_data.get("markdown", "")
            with open(cache_path, "w", encoding="utf-8") as fmd:
                fmd.write(md_content)
            print(f"  [✔] Hoàn thành Datalab conversion: {filename} -> Cache ({len(md_content)} ký tự)")
            return md_content
        elif status == "failed":
            raise RuntimeError(f"Datalab job thất bại cho {filename}: {res_data.get('error')}")

    raise TimeoutError(f"Datalab conversion hết thời gian chờ (timeout) cho {filename}")


def convert_all_gri_pdfs():
    """Chuyển đổi toàn bộ 42 file PDF GRI trong thư mục với rate-limit retry"""
    api_key = get_datalab_api_key()
    pdf_files = sorted(glob.glob(os.path.join(PDF_DIR, "*.pdf")))

    print(f"[+] Tìm thấy {len(pdf_files)} file PDF GRI. Đang hoàn thiện các file còn thiếu...")
    
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {executor.submit(convert_pdf_to_markdown, pdf_path, api_key): pdf_path for pdf_path in pdf_files}
        for future in as_completed(futures):
            pdf_path = futures[future]
            filename = os.path.basename(pdf_path)
            try:
                future.result()
            except Exception as e:
                print(f"  [-] Lỗi xử lý {filename}: {e}")

    print("[✔] Hoàn tất chuyển đổi Markdown toàn bộ 42 PDF!")


if __name__ == "__main__":
    convert_all_gri_pdfs()
