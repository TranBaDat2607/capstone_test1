# Hướng dẫn Tích hợp Dữ liệu Thật (Real Data Integration Guide)

Tài liệu này hướng dẫn chi tiết cách kết nối hệ thống **ESG Evidence View** với **dữ liệu thực tế** được trích xuất từ Knowledge Graph (Neo4j) hoặc các file kết quả từ Bước 6–8 của pipeline (`graph_output/crosscheck/`).

---

## 🔑 Nguyên tắc Vàng

> [!IMPORTANT]
> **Toàn bộ tầng Frontend (`frontend/index.html`, `frontend/css/style.css`, `frontend/js/app.js`) giữ nguyên 100%.**
> Việc chuyển đổi từ dữ liệu giả lập (mock data) sang dữ liệu thật **chỉ diễn ra tại file Backend (`api/evidence_service.py`)**.

---

## 1. Tổng quan Luồng Dữ liệu Thật

```
┌────────────────────────────────────────────────────────┐
│ 1. Pipeline Trích xuất (Step 1-6)                     │
│    BCTN & Báo chí ➔ LLM Cross-check (Step 7)          │
└──────────────────────────┬─────────────────────────────┘
                           │ Output
                           ▼
┌────────────────────────────────────────────────────────┐
│ 2. Nguồn dữ liệu thật                                  │
│    - Neo4j Knowledge Graph (Advisory Layer)            │
│    - Hoặc file graph_output/crosscheck/*.json           │
└──────────────────────────┬─────────────────────────────┘
                           │ API Call
                           ▼
┌────────────────────────────────────────────────────────┐
│ 3. Backend API (`api/evidence_service.py`)            │
│    Query ➔ Filter theo Year ➔ Mapping sang Response API │
└──────────────────────────┬─────────────────────────────┘
                           │ REST JSON Response
                           ▼
┌────────────────────────────────────────────────────────┐
│ 4. Frontend UI (`frontend/`)                           │
│    Hiển thị 3 Cột: ✅ Đúng | ❌ Sai | ⚠️ Bỏ qua        │
└────────────────────────────────────────────────────────┘
```

---

## 2. Các Nguồn Dữ liệu Thật Có thể Sử dụng

### Phương án A: Đọc từ File JSON Kết quả Crosscheck (Đơn giản nhất, không cần bật Neo4j)
Pipeline Bước 7 tự động xuất ra file kết quả tại:
- `graph_output/crosscheck/{ticker}_claim_assessments.json` (chứa toàn bộ tuyên bố + bằng chứng đối chiếu)
- `graph_output/crosscheck/{ticker}_crosscheck_stats.json` (chứa thống kê công ty)

### Phương án B: Query Trực tiếp từ Neo4j (Thời gian thực)
Nếu database Neo4j đang chạy (`docker compose up -d`), Backend có thể kết nối bằng `neo4j` Python driver để truy vấn các nút:
- `SustainabilityClaim` (Nút tuyên bố của công ty)
- Quan hệ `llm_supports`, `llm_contradicts` tới các nút bằng chứng `KPIObservation`, `MediaReport`, `Penalty`.

---

## 3. Quy tắc Ánh xạ Dữ liệu (Data Mapping Schema)

Để biến dữ liệu thật từ Pipeline thành chuẩn JSON hiển thị trên 3 Cột của UI, thực hiện ánh xạ theo bảng sau:

| Trường trên UI | Trường Dữ liệu Thật | Mô tả / Logic xử lý |
|---|---|---|
| **Cột 1: Thực hiện Đúng** | `assessment == "appears_supported"` | Lấy tuyên bố và danh sách `supporting_evidence` |
| **Cột 2: Thực tế Khác (Sai)** | `assessment == "appears_contradicted"` | Lấy tuyên bố và danh sách `contradicting_evidence` |
| **Cột 3: Bỏ qua Công bố** | `kpi_gap == true` hoặc `assessment == "unverified_insufficient_evidence"` | Lấy các chỉ tiêu bắt buộc TT96/GRI mà công ty không khai báo số liệu |
| **Trích dẫn Tuyên bố** | `claim_text` | Đoạn văn bản tuyên bố trích từ BCTN |
| **Nguồn trang BCTN** | `source_doc` & `source_page` | VD: "Báo cáo thường niên 2023, trang 42" |
| **Đơn vị / Nguồn xác minh** | `evidence.provider` hoặc `evidence.source_domain` | VD: "PwC Việt Nam", "Sở TN&MT Hải Dương", "vnexpress.net" |
| **Nội dung Kết luận** | `evidence.rationale` hoặc `evidence.text` | Nhận định đối soát từ mô hình LLM/Bằng chứng hành vi |
| **Mã Chỉ tiêu TT96/GRI** | `kpi_type` hoặc `standard_id` | Ghép nối với file `kpi_definitions_construction.json` |

---

## 4. Các Bước Thực hiện Tích hợp Backend

Khi bạn sẵn sàng chuyển sang data thật, hãy mở `api/evidence_service.py` và thực hiện 3 bước:

### Bước 1: Thêm hàm Đọc danh sách Công ty Thật
```python
# Thay vì danh sách COMPANIES cố định, quét tất cả file trong graph_output/crosscheck/
# hoặc query Neo4j để lấy danh sách ticker có sẵn.
def get_companies(query: str = ""):
    # Logic quét danh sách ticker từ graph_output/crosscheck/*.json
    ...
```

### Bước 2: Thêm hàm Đọc Claim Assessments từ File JSON
```python
def load_real_dossier_from_json(ticker: str) -> dict:
    file_path = REPO_ROOT / f"graph_output/crosscheck/{ticker.lower()}_claim_assessments.json"
    if file_path.exists():
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return []
```

### Bước 3: Phân loại Claim vào 3 Cột (Verified / Contradicted / Missing)
```python
def get_evidence(ticker: str, selected_year: Optional[str] = None):
    raw_claims = load_real_dossier_from_json(ticker)
    
    verified_list = []
    contradicted_list = []
    missing_list = []

    for c in raw_claims:
        # Lọc theo năm nếu user chọn năm cụ thể
        if selected_year and str(c.get("year")) != str(selected_year):
            continue
            
        item = {
            "year": str(c.get("year")),
            "standard_id": c.get("kpi_type", "TT96-ESG"),
            "standard_name": c.get("kpi_name", "Chỉ tiêu ESG"),
            "claim_quote": c.get("claim_text"),
            "claim_source": f"{c.get('source_doc', 'BCTN')}, trang {c.get('source_page', 'N/A')}",
            "verification": {
                "verifier": extract_verifier_name(c),
                "finding": extract_finding_text(c),
                "status": c.get("assessment")
            }
        }
        
        if c.get("assessment") == "appears_supported":
            verified_list.append(item)
        elif c.get("assessment") == "appears_contradicted":
            contradicted_list.append(item)
        elif c.get("kpi_gap") or c.get("assessment") == "unverified_insufficient_evidence":
            missing_list.append(item)

    # Đóng gói và trả về định dạng chuẩn cho Frontend
    return {
        "company": get_company_info(ticker),
        "selected_year": selected_year,
        "tabs": {
            "environment": { ... },
            "social": { ... },
            "governance": { ... }
        }
    }
```

---

## 5. Kiểm thử Tích hợp (Verification Plan)

1. **Chạy thử Pipeline**: Tạo file kết quả thật cho mã công ty (ví dụ: `AAA`).
2. **Khởi động Server**: `python api/main.py`
3. **Mở Trình duyệt**: Truy cập `http://localhost:8000`
4. **Kiểm tra**:
   - Nhập ticker `AAA` trên thanh Search.
   - Kiểm tra các thẻ hiển thị có khớp với nội dung trong `aaa_claim_assessments.json` hay không.
   - Chuyển năm `2023`, `2022` để đảm bảo dữ liệu thật lọc chính xác theo từng kỳ báo cáo.
