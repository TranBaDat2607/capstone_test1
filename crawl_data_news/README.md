# 📰 FPT News Crawler

Thu thập tin tức liên quan đến **Tập đoàn FPT** và các công ty thành viên từ các báo điện tử chính thống Việt Nam.

## 📋 Mô tả

Crawler tự động tìm kiếm và trích xuất các bài báo liên quan đến FPT từ **4 nguồn báo lớn**, lưu trữ theo cấu trúc thư mục phân loại theo năm. Dữ liệu thu thập phục vụ cho việc phân tích xu hướng truyền thông, nghiên cứu hình ảnh doanh nghiệp FPT qua các năm.

### Nguồn dữ liệu

| Nguồn | Phương thức tìm kiếm | Phương thức trích xuất |
|---|---|---|
| **VnExpress** | API tìm kiếm nội bộ + Google Search | httpx async |
| **Tuổi Trẻ** | API tìm kiếm nội bộ + Google Search | httpx async |
| **Thanh Niên** | Playwright (headless browser) + Google Search | httpx async |
| **VietnamNet** | API tìm kiếm nội bộ + Google Search | httpx async |

### Từ khóa tìm kiếm

Crawler tìm kiếm theo hệ thống từ khóa bao gồm:

- **Tập đoàn**: FPT, Tập đoàn FPT
- **Công ty con**: FPT Software, FPT Telecom, FPT IS, FPT Education, FPT Smart Cloud, FPT Digital, ...
- **Giáo dục**: FPT University, FPT Polytechnic, FUNiX, Đại học FPT, Cao đẳng FPT
- **Bán lẻ & dịch vụ**: FPT Retail, FPT Shop, FPT Long Châu, Synnex FPT, FPT Play, ...
- **Nhân vật**: Trương Gia Bình

## ⚙️ Tính năng chính

- **Crawl bất đồng bộ (Async)** — Sử dụng `httpx` với HTTP/2, crawl song song tới 8 request đồng thời
- **Stealth mode** — Rotate User-Agent, random delay giữa các request, xử lý tự động HTTP 429
- **Trích xuất nội dung thông minh** — Kết hợp 3 phương pháp theo thứ tự ưu tiên:
  1. `trafilatura` — extraction chất lượng cao
  2. `newspaper4k` — fallback extraction
  3. `BeautifulSoup` CSS selectors — fallback cuối cùng
- **Xử lý text toàn diện** — Decode HTML entities, normalize Unicode NFC (chuẩn tiếng Việt)
- **Trích xuất metadata đa lớp** — Meta tags → LD+JSON → CSS selectors → URL patterns → newspaper4k
- **Google Search bổ sung** — Tìm bài viết cũ (2010–2019) không có trên search nội bộ của báo
- **Phân loại theo năm** — Tự động xác định năm xuất bản và lưu vào thư mục tương ứng
- **Lọc nội dung** — Chỉ lưu bài thực sự liên quan đến FPT (kiểm tra keyword matching)

## 📁 Cấu trúc thư mục

```
crawl_data_news/
├── crawler_news.py          # Script crawler chính
├── requirements.txt         # Danh sách thư viện
├── crawl_summary.json       # Báo cáo tổng hợp sau mỗi lần crawl
├── README.md
├── 2007/                    # Bài viết năm 2007
│   ├── tuoitre_001.json
│   └── ...
├── 2009/
├── 2013/
├── ...
├── 2025/
│   ├── vnexpress_001.json
│   ├── vnexpress_002.json
│   ├── tuoitre_001.json
│   └── ...
└── 2026/
```

## 📄 Định dạng dữ liệu đầu ra

Mỗi bài viết được lưu thành 1 file JSON riêng biệt với cấu trúc:

```json
{
  "title": "Thành lập quỹ đầu tư Việt Nhật",
  "url": "https://tuoitre.vn/thanh-lap-quy-dau-tu-viet-nhat-231666.htm",
  "source": "Tuổi Trẻ",
  "published_date": "2007-11-29",
  "author": "KHIẾT HƯNG",
  "content": "Nội dung đầy đủ bài viết...",
  "summary": "200 ký tự đầu tiên của nội dung...",
  "keywords_matched": ["FPT", "FPT Capital"],
  "crawled_at": "2026-03-11T10:47:31.102307"
}
```

| Trường | Mô tả |
|---|---|
| `title` | Tiêu đề bài viết |
| `url` | Link gốc bài viết |
| `source` | Nguồn báo (VnExpress, Tuổi Trẻ, Thanh Niên, VietnamNet) |
| `published_date` | Ngày xuất bản (YYYY-MM-DD) |
| `author` | Tác giả bài viết |
| `content` | Nội dung toàn văn |
| `summary` | Tóm tắt (200 ký tự đầu) |
| `keywords_matched` | Danh sách từ khóa FPT khớp trong bài |
| `crawled_at` | Thời điểm crawl (ISO 8601) |

## 🚀 Cài đặt & Sử dụng

### Yêu cầu hệ thống

- Python ≥ 3.10
- Hệ điều hành: Windows / macOS / Linux

### 1. Cài đặt thư viện

```bash
pip install -r requirements.txt
```

### 2. Cài đặt Playwright browser (cho Thanh Niên)

```bash
playwright install chromium
```

### 3. Chạy crawler

```bash
python crawler_news.py
```

> **Lưu ý:** Mỗi lần chạy, crawler sẽ **xóa toàn bộ dữ liệu cũ** trong các thư mục năm và crawl lại từ đầu.

## ⚡ Cấu hình

Các tham số có thể tùy chỉnh trong phần `Config` của `crawler_news.py`:

| Tham số | Mặc định | Mô tả |
|---|---|---|
| `REQUEST_DELAY_MIN` | `0.5` | Delay tối thiểu giữa các request (giây) |
| `REQUEST_DELAY_MAX` | `1.5` | Delay tối đa giữa các request (giây) |
| `MAX_RETRIES` | `3` | Số lần retry tối đa khi request thất bại |
| `TIMEOUT` | `20` | Timeout cho mỗi request (giây) |
| `MAX_PAGES_PER_KEYWORD` | `3` | Số trang kết quả tìm kiếm tối đa mỗi keyword |
| `MAX_ARTICLES_PER_SOURCE` | `80` | Số bài tối đa crawl mỗi nguồn báo |
| `MIN_CONTENT_LENGTH` | `100` | Độ dài nội dung tối thiểu để lưu bài |
| `MAX_CONCURRENT` | `8` | Số request đồng thời tối đa |
| `CRAWL_YEARS` | `2010–2026` | Phạm vi năm crawl (chỉ áp dụng cho VnExpress) |

## 📦 Thư viện sử dụng

| Thư viện | Phiên bản | Mục đích |
|---|---|---|
| [httpx](https://www.python-httpx.org/) | ≥ 0.27.0 | HTTP client async với hỗ trợ HTTP/2 |
| [beautifulsoup4](https://www.crummy.com/software/BeautifulSoup/) | ≥ 4.12.0 | Phân tích cú pháp HTML |
| [lxml](https://lxml.de/) | ≥ 4.9.0 | Parser HTML/XML hiệu năng cao |
| [trafilatura](https://trafilatura.readthedocs.io/) | ≥ 1.8.0 | Trích xuất nội dung chính từ trang web |
| [newspaper4k](https://github.com/AndyTheFactory/newspaper4k) | ≥ 0.9.0 | Trích xuất bài viết & metadata |
| [playwright](https://playwright.dev/python/) | ≥ 1.40.0 | Headless browser cho trang render JS (Thanh Niên) |
