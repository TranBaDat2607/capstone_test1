# Ontology Schema — Vn-ESG-Graph

Định nghĩa cấu trúc dữ liệu chuẩn (Data Contract) cho toàn bộ pipeline của hệ thống Vn-ESG-Graph, từ giai đoạn trích xuất PDF cho đến lưu trữ Knowledge Graph và phát hiện Greenwashing.

## Cấu trúc thư mục

```
ontology/
├── ontology_schema.json   # Định nghĩa Entity Types và Relation Types
├── sample_instances.json  # Dữ liệu mẫu minh họa dựa theo FPT ESG 2023
└── README.md
```

## Entity Types

| Entity | Mô tả |
|--------|-------|
| `Company` | Doanh nghiệp niêm yết |
| `Metric` | Chỉ số ESG đo lường được (GRI 302, 305...) |
| `Target` | Mục tiêu cam kết dài hạn |
| `Regulation` | Quy định pháp lý (VD: TT96/2020/TT-BTC) |
| `Project` | Dự án ESG cụ thể |
| `Claim` | Tuyên bố định tính (cần kiểm tra greenwashing) |
| `DataPoint` | Số liệu thực tế từ bảng biểu trong báo cáo |
| `NewsEvent` | Tin tức bên ngoài |
| `Report` | Tài liệu báo cáo gốc (PDF) |

## Relation Types

| Relation | Chiều | Ý nghĩa |
|----------|-------|---------|
| `has_emission` | Company → Metric | Chỉ số phát thải |
| `targets_reduction` | Company → Target | Mục tiêu giảm thiểu |
| `complies_with` | Company → Regulation | Tuân thủ pháp lý |
| `invests_in` | Company → Project | Đầu tư dự án ESG |
| `claims_reduction` | Company → Claim | Tuyên bố cam kết |
| `supported_by` | Claim → DataPoint | Số liệu xác nhận tuyên bố |
| `contradicted_by` | Claim → NewsEvent | Tin tức phủ nhận tuyên bố (**Greenwashing flag**) |
| `extracted_from` | Metric/DataPoint/Claim → Report | Nguồn trích xuất |
| `mentions` | Report → Company | Báo cáo đề cập đến công ty |

## 3 Luồng nghiệp vụ chính

```
# Luồng 1 — Chỉ số phát thải
Company --[has_emission]--> Metric --[extracted_from]--> Report

# Luồng 2 — Tuân thủ & Cam kết
Company --[complies_with]--> Regulation
Company --[targets_reduction]--> Target
Company --[invests_in]--> Project

# Luồng 3 — Greenwashing Detection
Company --[claims_reduction]--> Claim
  Claim --[supported_by]--> DataPoint   (xác nhận → OK)
  Claim --[contradicted_by]--> NewsEvent (mâu thuẫn → GreenWash Alert)
```

## Chuẩn tham chiếu

- **GRI Standards**: [globalreporting.org](https://www.globalreporting.org) — Bộ tiêu chuẩn báo cáo bền vững quốc tế do GSSB phát triển. Các GRI code trong schema hiện tại (GRI 302, 305...) vẫn hợp lệ và được dùng song song trong giai đoạn chuyển tiếp 2026 — GRI 102 & 103 mới (ra 6/2025) chỉ bắt buộc từ 2027, nhưng cho phép early adoption.
- **Thông tư 96/2020/TT-BTC** + **Thông tư 08/2026/TT-BTC** (Bộ Tài chính, ban hành 03/02/2026): TT08/2026 là văn bản **mới nhất** sửa đổi bổ sung TT96 về công bố thông tin trên thị trường chứng khoán, hướng tới align với chuẩn ISSB và GRI. 2026 là năm bản lề khi ESG chuyển từ **khuyến nghị sang bắt buộc** tại Việt Nam.
- **Vietnam Sustainability Index (VNSI)**: Chỉ số bền vững do **HOSE** (Sở GDCK TP.HCM) quản lý, hợp tác với GIZ từ 2017. Danh mục VNSI 2024 gồm **20 cổ phiếu** có điểm bền vững cao nhất, cập nhật định kỳ tháng 7 hàng năm. Xem tại: [hsx.vn](https://www.hsx.vn)
- **Vietnam Green Taxonomy**: Quyết định 21/2025/QĐ-TTg của Thủ tướng Chính phủ (2025) thiết lập khung phân loại dự án đầu tư xanh — nền tảng pháp lý mới cho báo cáo ESG giai đoạn 2025-2030.
