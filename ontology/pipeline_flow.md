# Luồng Xử Lý Dữ Liệu — Vn-ESG-Graph Pipeline

> Giải thích cách hệ thống xử lý dữ liệu từ 2 nguồn đầu vào:
> báo cáo ESG nội bộ (PDF) và tin tức báo chí bên ngoài.

---

## Hai Nguồn Dữ Liệu Đầu Vào

| Nguồn | Ví dụ | Định dạng |
|-------|-------|---------|
| 📄 **Báo cáo nội bộ** | FPT ESG Report 2023, Annual Report | PDF |
| 📰 **Báo bên ngoài** | VnExpress, Lao Động, CafeF | Bài báo web (crawl về) |

---

## Bước 1 — Đọc và Hiểu Tài Liệu

### Từ báo cáo PDF:
Hệ thống mở từng file PDF, quét từng trang và nhận dạng 3 loại thông tin:

| Nội dung gặp trong PDF | Nhận dạng thành |
|------------------------|----------------|
| *"FPT cam kết giảm 30% cường độ carbon vào 2025"* | **Claim** — tuyên bố chưa kiểm chứng |
| Bảng trang 41: `Scope 1 \| 1,250 tonne CO2e \| 2023` | **DataPoint** + **Metric** |
| *"FPT tuân thủ Thông tư 96/2020"* | Quan hệ `complies_with → Regulation` |

### Từ báo bên ngoài:
Crawler thu thập bài báo, nhận dạng:

> Bài VnExpress: *"FPT bị phạt do xả thải tại Hòa Lạc, tháng 9/2023"*  
> → **NewsEvent** với `sentiment = Negative`, `pillar = E`

---

## Bước 2 — Chuyển Thành Các "Mảnh" Theo Schema

Mọi thông tin được chuẩn hóa thành **entity** và **relation** theo đúng cấu trúc Ontology Schema:

```
Báo cáo FPT 2023 (PDF)
    ↓
[Report: RPT_FPT_ESG_2023]
    ├──[extracted_from]── [Claim: "Cam kết giảm 30% carbon"]
    ├──[extracted_from]── [Metric: CO2 Scope 1 = 1,250 tonne]
    └──[extracted_from]── [DataPoint: cường độ carbon = 0.85 tCO2/tỷVNĐ]

Bài báo VnExpress (crawl)
    ↓
[NewsEvent: "FPT bị phạt xả thải"]
```

---

## Bước 3 — Lắp Các Mảnh Vào Đồ Thị Tri Thức (Neo4j)

Hệ thống nối tất cả entity lại với nhau bằng các relation:

```
COMP_FPT
  │
  ├──[has_emission]──────────► METRIC_CO2_SCOPE1_2023
  │
  ├──[claims_reduction]──────► CLM_E_001
  │                               "Cam kết giảm 30% cường độ carbon vào 2025"
  │                                    │
  │                                    └──[supported_by]──► DP_E_001
  │                                                         (cường độ = 0.85,
  │                                                          giảm so với baseline 1.12)
  │                                                         ✅ Claim được xác nhận
  │
  └──[claims_reduction]──────► CLM_G_001
                                  "Tuân thủ pháp lý, không vi phạm năm 2023"
                                       │
                                       └──[contradicted_by]──► NEWS_E_001
                                                               "FPT bị phạt xả thải 9/2023"
                                                               ⚠️ GREENWASHING FLAG!
```

---

## Bước 4 — Agent AI 

Agent quét toàn bộ đồ thị, phát hiện pattern nguy hiểm:

> *CLM_G_001 là tuyên bố Positive nhưng bị `contradicted_by` một NewsEvent Negative.*  
> → **Sự không nhất quán — gắn cờ Greenwashing!**

Agent tổng hợp thành **AuditResult** — output cuối cùng hiển thị trên Dashboard:

```json
{
  "id": "AUDIT_FPT_2023",
  "trust_score": 0.64,
  "greenwashing_risk": "Medium",
  "total_claims": 4,
  "supported_claims": 2,
  "flagged_claims": 2,
  "e_score": 0.60,
  "s_score": 0.55,
  "g_score": 0.75,
  "summary": "FPT có 2/4 tuyên bố thiếu căn cứ hoặc mâu thuẫn với tin tức bên ngoài."
}
```

---

## Tóm Tắt Vai Trò Các File Ontology

| File | Vai trò |
|------|---------|
| `ontology_schema.json` | **"Bản luật chơi"** — quy định hình dạng của từng entity/relation |
| `sample_instances.json` | **"Ví dụ thực tế"** — minh họa kết quả pipeline khi chạy với data FPT |

Khi pipeline hoạt động thật: PDF được đọc → trích xuất entity/relation → lưu vào Neo4j đúng theo cấu trúc schema → Agent truy vấn đồ thị → xuất AuditResult.

---

## Sơ Đồ Tổng Quan Pipeline

```
┌─────────────────┐    ┌─────────────────┐
│  ESG Report PDF │    │  Báo chí bên    │
│  Annual Report  │    │  ngoài (crawl)  │
└────────┬────────┘    └────────┬────────┘
         │                     │
         ▼                     ▼
┌─────────────────────────────────────────┐
│        Module 1: PDF Parser             │
│  (LayoutLMv3, Donut, OCR correction)    │
└────────────────────┬────────────────────┘
                     │ Text + Tables + Images
                     ▼
┌─────────────────────────────────────────┐
│        Module 2: RE & NLP               │
│  (ViGPT/PhoGPT + Constraint-based)     │
│  → Entity Recognition                  │
│  → Relation Extraction                 │
└────────────────────┬────────────────────┘
                     │ Entities + Relations (JSON)
                     ▼
┌─────────────────────────────────────────┐
│        Module 3: Knowledge Graph        │
│        Neo4j + GraphRAG                 │
│  → Lưu trữ đồ thị tri thức             │
│  → Entity Linking (đồng nhất tên)      │
└────────────────────┬────────────────────┘
                     │ Graph queries
                     ▼
┌─────────────────────────────────────────┐
│        Module 4: Agentic AI             │
│        LangGraph Multi-Agent            │
│  → Phát hiện Greenwashing               │
│  → Tính Trust Score                    │
│  → Tạo AuditResult                     │
└────────────────────┬────────────────────┘
                     │
                     ▼
              📊 Dashboard
```
