# -*- coding: utf-8 -*-
"""
Vietnamese News Crawler - Crawl bài báo liên quan đến ESG cho danh sách công ty.

Nguồn tìm kiếm:
  - Google News (RSS feed)
  - VNExpress
  - Tuổi Trẻ
  - Thanh Niên
  - Dân Trí

Output: file JSON với format:
  {
    "url": "...",
    "title": "...",
    "source": "...",
    "date_crawled": "...",
    "content_markdown": "..."
  }

Sử dụng:
  python crawler.py
  python crawler.py --company "FPT" --max-articles 10
  python crawler.py --delay 3 --output output/results.json
"""

import io
import sys

# Fix Windows console encoding for Vietnamese/Unicode output
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import requests

from bs4 import BeautifulSoup

import html2text
import json
import time
import logging
import os
import re
import base64
import argparse
from datetime import datetime
from urllib.parse import quote_plus, urlparse

from config import COMPANIES

# ============================================================
# CẤU HÌNH MẶC ĐỊNH
# ============================================================
DEFAULT_DELAY = 3             # Giây giữa các request
DEFAULT_MAX_RETRIES = 3      # Số lần retry khi request thất bại
DEFAULT_TIMEOUT = 20         # Timeout cho mỗi request (giây)
DEFAULT_MAX_ARTICLES = 30    # Số bài tối đa mỗi công ty
DEFAULT_OUTPUT_DIR = "output"
DEFAULT_OUTPUT_FILE = "articles.json"
DEFAULT_PROGRESS_FILE = "progress.json"
DEFAULT_LOG_FILE = "crawler.log"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate",
    "Connection": "keep-alive",
}


# ============================================================
# LOGGING SETUP
# ============================================================
def setup_logging(log_file):
    """Cấu hình logging ra file + console."""
    logger = logging.getLogger("crawler")
    logger.setLevel(logging.INFO)

    # File handler
    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setLevel(logging.INFO)
    fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))

    # Console handler
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))

    logger.addHandler(fh)
    logger.addHandler(ch)
    return logger


# ============================================================
# TIỆN ÍCH
# ============================================================
def extract_search_name(company_name):
    """
    Trích xuất tên tìm kiếm ngắn gọn từ tên đầy đủ của công ty.

    Ví dụ:
      "CTCP Tập đoàn ASG" -> "Tập đoàn ASG"
      "CTCP FPT" -> "FPT"
      "Tổng Công ty Hàng không Việt Nam - CTCP" -> "Hàng không Việt Nam"
    """
    name = company_name.strip()

    # Xử lý đặc biệt cho ngân hàng: bỏ "TMCP" nhưng giữ "Ngân hàng"
    if name.startswith("Ngân hàng TMCP "):
        return "Ngân hàng " + name[len("Ngân hàng TMCP "):]

    # Loại bỏ prefix phổ biến
    prefixes = [
        "CTCP - Tổng Công ty ",
        "CTCP - Tổng công ty ",
        "Tổng Công ty cổ phần ",
        "Tổng công ty cổ phần ",
        "Tổng Công ty ",
        "Tổng công ty ",
        "Tập đoàn ",
        "Công ty Tài chính Tổng hợp Cổ phần ",
        "Công ty ",
        "CTCP - ",
        "CTCP ",
    ]
    for prefix in prefixes:
        if name.startswith(prefix):
            name = name[len(prefix):]
            break

    # Loại bỏ suffix phổ biến
    suffixes = [" - CTCP", " CTCP"]
    for suffix in suffixes:
        if name.endswith(suffix):
            name = name[: -len(suffix)]
            break

    return name.strip()


def make_request(url, delay, timeout=DEFAULT_TIMEOUT, retries=DEFAULT_MAX_RETRIES,
                 logger=None):
    """Thực hiện HTTP GET request với retry logic."""
    for attempt in range(retries):
        try:
            resp = requests.get(
                url, headers=HEADERS, timeout=timeout, allow_redirects=True
            )
            resp.raise_for_status()
            return resp
        except requests.exceptions.HTTPError as e:
            status = e.response.status_code if e.response else "?"
            if logger:
                logger.warning(
                    f"  HTTP {status} (attempt {attempt+1}/{retries}): {url}"
                )
            # 403/429 -> chờ lâu hơn
            if status in (403, 429):
                time.sleep(delay * (attempt + 2))
            elif attempt < retries - 1:
                time.sleep(delay)
        except requests.RequestException as e:
            if logger:
                logger.warning(
                    f"  Request error (attempt {attempt+1}/{retries}): "
                    f"{type(e).__name__}: {e}"
                )
            if attempt < retries - 1:
                time.sleep(delay * (attempt + 1))
    return None


def resolve_google_news_url(url, delay, logger=None):
    """
    Google News RSS trả về URL encoded (protobuf + base64).
    Hàm này decode để lấy URL bài báo gốc sử dụng Google batchexecute API.
    """
    if "news.google.com" not in url:
        return url

    batchexecute_headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/125.0.0.0 Safari/537.36"
        )
    }

    # Cách 1 (Chính): Sử dụng batchexecute API của Google
    try:
        # Fetch trang redirect của Google News
        resp = requests.get(url, headers=batchexecute_headers, timeout=10)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, 'html.parser')

        # Lấy attribute data-p chứa tham số mã hóa
        data_element = soup.select_one('c-wiz[data-p]')
        if data_element:
            data_p = data_element.get('data-p')
            # Tạo payload cho batchexecute
            obj = json.loads(data_p.replace('%.@.', '["garturlreq",'))
            payload = {
                'f.req': json.dumps([[["Fbv4je", json.dumps(obj[:-6] + obj[-2:]), "null", "generic"]]])
            }

            # Gửi POST request đến batchexecute endpoint
            post_headers = {
                'content-type': 'application/x-www-form-urlencoded;charset=UTF-8',
                'user-agent': batchexecute_headers['User-Agent']
            }
            post_url = "https://news.google.com/_/DotsSplashUi/data/batchexecute"

            response = requests.post(post_url, headers=post_headers, data=payload, timeout=10)
            response.raise_for_status()

            # Parse kết quả trả về để lấy URL thật
            cleaned_text = response.text.replace(")]}'", "").strip()
            data = json.loads(cleaned_text)
            array_string = data[0][2]
            real_url = json.loads(array_string)[1]

            if real_url and "google.com" not in real_url:
                if logger:
                    logger.debug(f"  Decoded Google News URL via batchexecute: {real_url}")
                return real_url
    except Exception as e:
        if logger:
            logger.debug(f"  Không thể decode Google News URL qua batchexecute: {e}")

    # Cách 2 (Fallback): Decode base64 thô từ path /articles/...
    match = re.search(r'/articles/([^?&]+)', url)
    if match:
        encoded = match.group(1)
        padding = 4 - len(encoded) % 4
        if padding != 4:
            encoded += '=' * padding
        try:
            decoded = base64.urlsafe_b64decode(encoded)
            decoded_str = decoded.decode('latin-1')
            found_urls = re.findall(
                r'https?://[a-zA-Z0-9._\-/:%?&=#~@!$\'\(\)\*\+,;]+',
                decoded_str,
            )
            for found in found_urls:
                if 'google.com' not in found and 'google.' not in found:
                    return found
        except Exception:
            pass

    return url



# ============================================================
# ARTICLE EXTRACTOR - Trích xuất nội dung bài báo
# ============================================================
class ArticleExtractor:
    """Trích xuất nội dung bài báo từ các trang báo Việt Nam."""

    def __init__(self, delay, logger):
        self.delay = delay
        self.logger = logger
        self.h2t = html2text.HTML2Text()
        self.h2t.ignore_links = False
        self.h2t.ignore_images = True
        self.h2t.body_width = 0
        self.h2t.unicode_snob = True
        self.h2t.skip_internal_links = True

    def extract(self, url):
        """
        Trích xuất bài báo từ URL.
        Returns: dict với format chuẩn hoặc None nếu thất bại.
        """
        resp = make_request(url, self.delay, logger=self.logger)
        if not resp:
            return None

        try:
            resp.encoding = resp.apparent_encoding or "utf-8"
            soup = BeautifulSoup(resp.text, "lxml")
        except Exception as e:
            self.logger.error(f"  Parse HTML thất bại: {url} - {e}")
            return None

        domain = urlparse(url).netloc.lower()

        # Chọn extractor theo domain
        extractors = {
            "vnexpress.net": self._extract_vnexpress,
            "tuoitre.vn": self._extract_tuoitre,
            "thanhnien.vn": self._extract_thanhnien,
            "dantri.com.vn": self._extract_dantri,
            "cafef.vn": self._extract_cafef,
            "vietstock.vn": self._extract_vietstock,
        }

        for key, func in extractors.items():
            if key in domain:
                return func(soup, url)

        return self._extract_generic(soup, url)

    # ------ VNExpress ------
    def _extract_vnexpress(self, soup, url):
        title = self._get_title(
            soup,
            [("h1", {"class": "title-detail"}), ("h1", {})],
        )
        content_div = (
            soup.find("article", class_="fck_detail")
            or soup.find("div", class_="fck_detail")
        )
        content_md = self._clean_and_convert(content_div, r"box-relate|ads|banner")

        if not title and not content_md:
            return None

        return self._build_article(url, title, "VNExpress", content_md)

    # ------ Tuổi Trẻ ------
    def _extract_tuoitre(self, soup, url):
        title = self._get_title(
            soup,
            [
                ("h1", {"class": "detail-title"}),
                ("h1", {"class": "article-title"}),
                ("h1", {}),
            ],
        )
        content_div = (
            soup.find("div", class_="detail-content")
            or soup.find("div", id="main-detail-body")
            or soup.find("div", class_="content fck")
        )
        content_md = self._clean_and_convert(
            content_div, r"relate|VCSortableIn|ads|banner"
        )

        if not title and not content_md:
            return None

        return self._build_article(url, title, "Tuổi Trẻ", content_md)

    # ------ Thanh Niên ------
    def _extract_thanhnien(self, soup, url):
        title = self._get_title(
            soup,
            [
                ("h1", {"class": "detail-title"}),
                ("h1", {"class": "details__headline"}),
                ("h1", {}),
            ],
        )
        content_div = (
            soup.find("div", class_="detail__content")
            or soup.find("div", class_="detail-content")
            or soup.find("div", id="abody")
        )
        content_md = self._clean_and_convert(
            content_div, r"relate|ads|banner|box-tinlienquan"
        )

        if not title and not content_md:
            return None

        return self._build_article(url, title, "Thanh Niên", content_md)

    # ------ Dân Trí ------
    def _extract_dantri(self, soup, url):
        title = self._get_title(
            soup,
            [
                ("h1", {"class": "title-page"}),
                ("h1", {"class": "e-magazine__title"}),
                ("h1", {}),
            ],
        )
        content_div = (
            soup.find("div", class_="singular-content")
            or soup.find("div", class_="e-magazine__body")
            or soup.find("div", class_="detail-content")
            or soup.find("div", id="desktop-in-article")
            or soup.find("article", class_=re.compile(r"dt-flex.*"))
        )
        content_md = self._clean_and_convert(content_div, r"relate|ads|banner")

        if not title and not content_md:
            return None

        return self._build_article(url, title, "Dân Trí", content_md)

    # ------ CafeF ------
    def _extract_cafef(self, soup, url):
        if "/du-lieu/" in url or "/doanh-nghiep/" in url:
            return None

        title = self._get_title(
            soup,
            [
                ("h1", {"class": "title-detail"}),
                ("h1", {"class": "title"}),
                ("h1", {}),
            ],
        )
        content_div = (
            soup.find("div", class_="detail-content")
            or soup.find("div", class_="totalcontentdetail")
            or soup.find("div", id="contentdetail")
            or soup.find("div", id="mainContent")
        )
        content_md = self._clean_and_convert(
            content_div, r"relate|ads|banner|comment|sidebar|link-content-chan|xem-them"
        )

        if not title and not content_md:
            return None

        return self._build_article(url, title, "Cafef", content_md)

    # ------ Vietstock ------
    def _extract_vietstock(self, soup, url):
        title = self._get_title(
            soup,
            [
                ("h1", {"class": "article-title"}),
                ("h1", {"class": "title"}),
                ("h1", {}),
            ],
        )
        content_div = (
            soup.find("div", id="article-content")
            or soup.find("div", class_="article-content")
            or soup.find("div", class_="article-release")
        )
        content_md = self._clean_and_convert(
            content_div, r"relate|ads|banner|comment|sidebar|related-news"
        )

        if not title and not content_md:
            return None

        return self._build_article(url, title, "Vietstock", content_md)

    # ------ Generic (fallback) ------
    def _extract_generic(self, soup, url):
        title = self._get_title(soup, [("h1", {})])
        if not title and soup.title:
            title = soup.title.get_text(strip=True)

        candidates = []
        
        articles = soup.find_all("article")
        if articles:
            candidates.extend(articles)
            
        divs = soup.find_all("div", class_=re.compile(r"article|content|body|post|entry", re.I))
        candidates.extend(divs)
        
        divs_id = soup.find_all("div", id=re.compile(r"article|content|body|post|entry", re.I))
        candidates.extend(divs_id)

        best_content_div = None
        max_text_len = 0
        
        for candidate in candidates:
            paragraphs = candidate.find_all('p')
            p_text_len = sum(len(p.get_text(strip=True)) for p in paragraphs)
            
            if p_text_len > max_text_len:
                max_text_len = p_text_len
                best_content_div = candidate

        if not best_content_div:
            for candidate in candidates:
                if candidate.name in ['body', 'html']:
                    continue
                classes = candidate.get('class', [])
                if any(c in ['wrapper', 'container', 'page', 'site'] for c in (classes if isinstance(classes, list) else [classes])):
                    continue
                
                text_len = len(candidate.get_text(strip=True))
                if text_len > max_text_len and text_len < 100000:
                    max_text_len = text_len
                    best_content_div = candidate

        content_md = ""
        if best_content_div:
            import copy
            content_div_clean = copy.copy(best_content_div)
            
            for el in content_div_clean.find_all(["nav", "footer", "aside", "script", "style", "iframe"]):
                el.decompose()
            for el in content_div_clean.find_all(
                ["div", "section"],
                class_=re.compile(r"ads|banner|comment|relate|share|social|sidebar|widget|recommend", re.I),
            ):
                el.decompose()
            content_md = self.h2t.handle(str(content_div_clean)).strip()

        domain = urlparse(url).netloc.replace("www.", "")
        source = domain.split(".")[0].title()

        if not title and not content_md:
            return None

        return self._build_article(url, title, source, content_md)

    # ------ Helper methods ------
    def _get_title(self, soup, selectors):
        """Thử lần lượt các selector để lấy title."""
        for tag, attrs in selectors:
            el = soup.find(tag, attrs) if attrs else soup.find(tag)
            if el:
                return el.get_text(strip=True)
        return ""

    def _clean_and_convert(self, content_div, remove_pattern):
        """Loại bỏ element không mong muốn và chuyển sang markdown."""
        if not content_div:
            return ""
        # Loại bỏ script, style
        for el in content_div.find_all(["script", "style", "iframe"]):
            el.decompose()
        # Loại bỏ theo pattern
        if remove_pattern:
            for el in content_div.find_all(
                ["div", "figure", "aside"],
                class_=re.compile(remove_pattern),
            ):
                el.decompose()
        return self.h2t.handle(str(content_div)).strip()

    def _build_article(self, url, title, source, content_md):
        """Tạo dict bài báo theo format chuẩn."""
        return {
            "url": url,
            "title": title,
            "source": source,
            "date_crawled": datetime.now().isoformat(),
            "content_markdown": content_md,
        }


# ============================================================
# SEARCH ENGINE - Tìm kiếm bài báo từ nhiều nguồn
# ============================================================
class SearchEngine:
    """Tìm kiếm bài báo từ Google News và các trang báo Việt Nam."""

    def __init__(self, delay, logger):
        self.delay = delay
        self.logger = logger

    def search_google_news(self, query, num_results=5):
        """Tìm kiếm qua Google News RSS feed (miễn phí, không cần API key)."""
        # Thêm filter thời gian: lấy bài trong 2 năm gần nhất (tăng từ 6m để lấy nhiều bài ESG hơn)
        query_with_time = f"{query} when:2y"
        encoded = quote_plus(query_with_time)
        url = (
            f"https://news.google.com/rss/search?"
            f"q={encoded}&hl=vi&gl=VN&ceid=VN:vi"
        )

        resp = make_request(url, self.delay, logger=self.logger)
        if not resp:
            return []

        try:
            soup = BeautifulSoup(resp.content, "lxml-xml")
            items = soup.find_all("item")[:num_results]

            results = []
            for item in items:
                title_tag = item.find("title")
                link_tag = item.find("link")

                if link_tag:
                    # Google News RSS: link nằm ngay sau tag <link>
                    raw_url = link_tag.next_sibling
                    if raw_url and isinstance(raw_url, str):
                        article_url = raw_url.strip()
                    else:
                        article_url = link_tag.get_text(strip=True)

                    if article_url:
                        # Resolve Google News redirect
                        real_url = resolve_google_news_url(
                            article_url, self.delay, self.logger
                        )
                        results.append(
                            {
                                "url": real_url,
                                "title": (
                                    title_tag.get_text(strip=True)
                                    if title_tag
                                    else ""
                                ),
                            }
                        )

            return results
        except Exception as e:
            self.logger.error(f"  Lỗi parse Google News RSS: {e}")
            return []

    def search_vnexpress(self, query, num_results=5):
        """Tìm kiếm trên VNExpress."""
        encoded = quote_plus(query)
        url = f"https://timkiem.vnexpress.net/?q={encoded}"

        resp = make_request(url, self.delay, logger=self.logger)
        if not resp:
            return []

        try:
            soup = BeautifulSoup(resp.text, "lxml")
            results = []

            # VNExpress search results
            articles = soup.find_all("article", class_="item-news")[:num_results]
            for article in articles:
                link = article.find("a", class_="title-news")
                if not link:
                    link = article.find("h3")
                    if link:
                        link = link.find("a")
                if link and link.get("href"):
                    results.append(
                        {
                            "url": link["href"],
                            "title": link.get_text(strip=True),
                        }
                    )

            return results
        except Exception as e:
            self.logger.error(f"  Lỗi search VNExpress: {e}")
            return []

    def search_tuoitre(self, query, num_results=5):
        """Tìm kiếm trên Tuổi Trẻ."""
        encoded = quote_plus(query)
        url = f"https://tuoitre.vn/tim-kiem.htm?keywords={encoded}"

        resp = make_request(url, self.delay, logger=self.logger)
        if not resp:
            return []

        try:
            soup = BeautifulSoup(resp.text, "lxml")
            results = []

            items = soup.find_all(
                ["li", "div"],
                class_=re.compile(r"news-item|item-news"),
            )[:num_results]

            for item in items:
                a_tag = item.find("a")
                if a_tag and a_tag.get("href"):
                    href = a_tag["href"]
                    if not href.startswith("http"):
                        href = f"https://tuoitre.vn{href}"
                    title_tag = item.find(["h3", "h2"]) or a_tag
                    results.append(
                        {
                            "url": href,
                            "title": title_tag.get_text(strip=True),
                        }
                    )

            return results
        except Exception as e:
            self.logger.error(f"  Lỗi search Tuổi Trẻ: {e}")
            return []

    def search_thanhnien(self, query, num_results=5):
        """Tìm kiếm trên Thanh Niên."""
        encoded = quote_plus(query)
        url = f"https://thanhnien.vn/tim-kiem?q={encoded}"

        resp = make_request(url, self.delay, logger=self.logger)
        if not resp:
            return []

        try:
            soup = BeautifulSoup(resp.text, "lxml")
            results = []

            items = soup.find_all(
                ["div", "article"],
                class_=re.compile(r"story|item-news|search-result"),
            )[:num_results]

            for item in items:
                a_tag = item.find("a")
                if a_tag and a_tag.get("href"):
                    href = a_tag["href"]
                    if not href.startswith("http"):
                        href = f"https://thanhnien.vn{href}"
                    title_tag = item.find(["h2", "h3"]) or a_tag
                    results.append(
                        {
                            "url": href,
                            "title": title_tag.get_text(strip=True),
                        }
                    )

            return results
        except Exception as e:
            self.logger.error(f"  Lỗi search Thanh Niên: {e}")
            return []

    def search_dantri(self, query, num_results=5):
        """Tìm kiếm trên Dân Trí."""
        encoded = quote_plus(query)
        url = f"https://dantri.com.vn/tim-kiem?query={encoded}"

        resp = make_request(url, self.delay, logger=self.logger)
        if not resp:
            return []

        try:
            soup = BeautifulSoup(resp.text, "lxml")
            results = []

            items = soup.find_all(
                ["article", "div"],
                class_=re.compile(r"article-item|search-item|news-item"),
            )[:num_results]

            for item in items:
                a_tag = item.find("a")
                if a_tag and a_tag.get("href"):
                    href = a_tag["href"]
                    if not href.startswith("http"):
                        href = f"https://dantri.com.vn{href}"
                    title_tag = item.find(["h3", "h2"]) or a_tag
                    results.append(
                        {
                            "url": href,
                            "title": title_tag.get_text(strip=True),
                        }
                    )

            return results
        except Exception as e:
            self.logger.error(f"  Lỗi search Dân Trí: {e}")
            return []


# ============================================================
# MAIN CRAWLER
# ============================================================
class NewsCrawler:
    """
    Crawler chính - điều phối tìm kiếm và trích xuất bài báo.

    Tính năng:
      - Tìm kiếm đa nguồn (Google News + 4 báo VN)
      - Rate limiting (chờ giữa các request)
      - Retry khi lỗi
      - Lưu tiến trình (resume khi bị gián đoạn)
      - Loại trùng URL
      - Kiểm tra keyword trong nội dung
    """

    def __init__(self, companies=None, delay=DEFAULT_DELAY,
                 max_articles=DEFAULT_MAX_ARTICLES,
                 output_dir=DEFAULT_OUTPUT_DIR, output_file=DEFAULT_OUTPUT_FILE,
                 log_file=DEFAULT_LOG_FILE):

        self.companies = companies or COMPANIES
        self.delay = delay
        self.max_articles = max_articles
        self.output_dir = output_dir
        self.output_path = os.path.join(output_dir, output_file)
        self.progress_path = os.path.join(output_dir, DEFAULT_PROGRESS_FILE)

        # Setup logging
        os.makedirs(output_dir, exist_ok=True)
        self.logger = setup_logging(os.path.join(output_dir, log_file))

        # Khởi tạo engines
        self.search = SearchEngine(delay, self.logger)
        self.extractor = ArticleExtractor(delay, self.logger)

        # State
        self.crawled_urls = set()
        self.crawled_titles = set()  # Dedup theo tiêu đề bài báo
        self.articles = []
        self.completed_companies = set()
        self.stats = {
            "total_queries": 0,
            "total_urls_found": 0,
            "total_extracted": 0,
            "total_relevant": 0,
            "total_failed": 0,
        }

        # Load tiến trình trước đó (nếu có)
        self._load_progress()

    # ------ Quản lý tiến trình ------
    def _load_progress(self):
        """Load tiến trình đã crawl trước đó để hỗ trợ resume."""
        if os.path.exists(self.output_path):
            try:
                with open(self.output_path, "r", encoding="utf-8") as f:
                    existing = json.load(f)
                self.articles = existing
                self.crawled_urls = {a["url"] for a in existing}
                self.crawled_titles = {
                    a["title"].strip().lower()
                    for a in existing if a.get("title")
                }
                self.logger.info(
                    f"Đã load {len(existing)} bài báo từ lần crawl trước"
                )
            except Exception as e:
                self.logger.warning(f"Không thể load file output cũ: {e}")

        if os.path.exists(self.progress_path):
            try:
                with open(self.progress_path, "r", encoding="utf-8") as f:
                    progress = json.load(f)
                self.crawled_urls.update(progress.get("crawled_urls", []))
                self.completed_companies = set(
                    progress.get("completed_companies", [])
                )
                self.logger.info(
                    f"Đã load tiến trình: {len(self.completed_companies)} "
                    f"công ty đã hoàn thành"
                )
            except Exception as e:
                self.logger.warning(f"Không thể load file progress cũ: {e}")

    def _save_progress(self):
        """Lưu tiến trình hiện tại."""
        os.makedirs(self.output_dir, exist_ok=True)

        # Lưu bài báo
        with open(self.output_path, "w", encoding="utf-8") as f:
            json.dump(self.articles, f, ensure_ascii=False, indent=2)

        # Lưu tiến trình
        with open(self.progress_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "crawled_urls": list(self.crawled_urls),
                    "completed_companies": list(self.completed_companies),
                    "last_updated": datetime.now().isoformat(),
                },
                f,
                ensure_ascii=False,
                indent=2,
            )



    def _mentions_company(self, text, company_name, search_name):
        """
        Kiểm tra bài báo có nhắc đến công ty không.
        So khớp với: tên đầy đủ, tên rút gọn, hoặc các phần tên quan trọng.
        """
        text_lower = text.lower()

        # Check tên đầy đủ
        if company_name.lower() in text_lower:
            return True

        # Check tên rút gọn (search_name)
        if search_name.lower() in text_lower:
            return True

        # Check từng từ quan trọng trong search_name (>= 3 ký tự)
        # Ví dụ: "Tập đoàn Hòa Phát" -> check "Hòa Phát"
        words = search_name.split()
        # Lấy các từ viết hoa (tên riêng) hoặc từ dài >= 3
        important_parts = [w for w in words if len(w) >= 3 and w[0].isupper()]
        if len(important_parts) >= 2:
            # Ghép các từ quan trọng thành cụm
            combined = " ".join(important_parts)
            if combined.lower() in text_lower:
                return True

        return False

    # ------ Tìm kiếm đa nguồn ------
    def _search_all_sources(self, query):
        """
        Tìm kiếm trên tất cả các nguồn và trả về danh sách kết quả.
        Mỗi kết quả: {"url": "...", "title": "..."}
        """
        all_results = []
        sources = [
            ("Google News", self.search.search_google_news, 5),
            ("VNExpress", self.search.search_vnexpress, 3),
            ("Tuổi Trẻ", self.search.search_tuoitre, 3),
            ("Thanh Niên", self.search.search_thanhnien, 3),
            ("Dân Trí", self.search.search_dantri, 3),
        ]

        for source_name, search_func, num in sources:
            self.logger.info(f"    [SEARCH] {source_name}: \"{query}\"")
            try:
                results = search_func(query, num_results=num)
                all_results.extend(results)
                self.stats["total_urls_found"] += len(results)
                self.logger.info(f"       -> {len(results)} kết quả")
            except Exception as e:
                self.logger.error(f"    Lỗi tìm kiếm {source_name}: {e}")

            time.sleep(self.delay)

        self.stats["total_queries"] += 1
        return all_results

    # ------ Crawl một công ty ------
    def crawl_company(self, company_name):
        """Crawl tất cả bài báo liên quan đến một công ty."""
        search_name = extract_search_name(company_name)

        self.logger.info(f"\n{'='*70}")
        self.logger.info(f"CÔNG TY: {company_name}")
        self.logger.info(f"   Tên tìm kiếm: {search_name}")
        self.logger.info(f"{'='*70}")

        company_articles = []
        seen_urls = set()
        seen_titles = set()

        # Tìm kiếm trực tiếp bằng tên công ty (không dùng từ khóa ESG)
        self.logger.info(f"\n  Tìm kiếm bài báo về: \"{search_name}\"")
        results = self._search_all_sources(search_name)

        # Trích xuất từng bài báo
        for result in results:
            url = result["url"]

            # Bỏ qua URL trùng lặp
            if url in self.crawled_urls or url in seen_urls:
                continue

            # Bỏ qua bài có tiêu đề trùng
            result_title = result.get("title", "").strip().lower()
            if result_title and (
                result_title in self.crawled_titles
                or result_title in seen_titles
            ):
                continue

            # Bỏ qua URL không phải bài báo
            if any(
                skip in url
                for skip in [
                    "google.com",
                    "youtube.com",
                    "facebook.com",
                    "tiktok.com",
                    "/video/",
                    "/photo/",
                ]
            ):
                continue

            seen_urls.add(url)

            if len(company_articles) >= self.max_articles:
                self.logger.info(
                    f"  Đã đạt giới hạn {self.max_articles} bài, "
                    f"chuyển công ty tiếp theo"
                )
                break

            # Trích xuất nội dung
            self.logger.info(f"  Đang trích xuất: {url[:100]}...")
            article = self.extractor.extract(url)
            time.sleep(self.delay)

            if article:
                self.stats["total_extracted"] += 1

                # Chỉ kiểm tra: bài có nhắc đến tên công ty không
                full_text = f"{article['title']} {article['content_markdown']}"
                has_company = self._mentions_company(
                    full_text, company_name, search_name
                )

                if has_company:
                    article["company"] = company_name
                    company_articles.append(article)
                    self.articles.append(article)
                    self.crawled_urls.add(url)
                    title_key = article["title"].strip().lower()
                    self.crawled_titles.add(title_key)
                    seen_titles.add(title_key)
                    self.stats["total_relevant"] += 1
                    self.logger.info(
                        f"  [OK] Đã lưu: {article['title'][:80]}"
                    )
                else:
                    self.crawled_urls.add(url)
                    self.logger.info(
                        f"  Không nhắc đến công ty, bỏ qua"
                    )
            else:
                self.stats["total_failed"] += 1
                self.crawled_urls.add(url)  # Đánh dấu để không thử lại
                self.logger.warning(f"  Không thể trích xuất nội dung")

        # Lưu tiến trình sau mỗi công ty
        self.completed_companies.add(company_name)
        self._save_progress()

        self.logger.info(
            f"\n  Kết quả cho {search_name}: "
            f"{len(company_articles)} bài báo"
        )

        return company_articles

    # ------ Chạy crawler ------
    def run(self):
        """Chạy crawler cho tất cả các công ty."""
        self.logger.info(f"\n{'#'*70}")
        self.logger.info(f"# VIETNAMESE NEWS CRAWLER - TẤT CẢ BÀI BÁO")
        self.logger.info(f"# Số công ty: {len(self.companies)}")
        self.logger.info(f"# Max bài/công ty: {self.max_articles}")
        self.logger.info(f"# Delay: {self.delay}s")
        self.logger.info(f"# Output: {self.output_path}")
        self.logger.info(f"{'#'*70}\n")

        start_time = time.time()
        total = len(self.companies)

        for i, company in enumerate(self.companies, 1):
            # Bỏ qua công ty đã hoàn thành
            if company in self.completed_companies:
                self.logger.info(
                    f"[{i}/{total}] Bỏ qua (đã crawl): {company}"
                )
                continue

            self.logger.info(f"\n[{i}/{total}] Đang xử lý: {company}")

            try:
                self.crawl_company(company)
            except KeyboardInterrupt:
                self.logger.info(
                    "\n\nCrawler bị dừng bởi người dùng. "
                    "Đang lưu tiến trình..."
                )
                self._save_progress()
                self.logger.info(
                    f"Đã lưu {len(self.articles)} bài báo. "
                    f"Chạy lại để tiếp tục từ chỗ dừng."
                )
                return
            except Exception as e:
                self.logger.error(
                    f"Lỗi không xử lý được cho {company}: {e}",
                    exc_info=True,
                )
                continue

        # Lưu kết quả cuối cùng
        self._save_progress()

        elapsed = time.time() - start_time
        hours = int(elapsed // 3600)
        minutes = int((elapsed % 3600) // 60)
        seconds = int(elapsed % 60)

        self.logger.info(f"\n{'#'*70}")
        self.logger.info(f"# CRAWLING HOÀN THÀNH")
        self.logger.info(f"{'#'*70}")
        self.logger.info(f"  Tổng bài báo:       {len(self.articles)}")
        self.logger.info(f"  Tổng queries:        {self.stats['total_queries']}")
        self.logger.info(f"  URL tìm được:        {self.stats['total_urls_found']}")
        self.logger.info(f"  Bài trích xuất OK:   {self.stats['total_extracted']}")
        self.logger.info(f"  Bài liên quan ESG:   {self.stats['total_relevant']}")
        self.logger.info(f"  Bài thất bại:        {self.stats['total_failed']}")
        self.logger.info(f"  Thời gian:           {hours}h {minutes}m {seconds}s")
        self.logger.info(f"  File output:         {self.output_path}")
        self.logger.info(f"{'#'*70}")


# ============================================================
# ENTRY POINT
# ============================================================
def main():
    parser = argparse.ArgumentParser(
        description="Vietnamese News Crawler - Crawl bài báo ESG",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ví dụ sử dụng:
  python crawler.py                           # Crawl tất cả công ty
  python crawler.py --company "FPT"           # Chỉ crawl công ty có tên chứa "FPT"
  python crawler.py --max-articles 10         # Giới hạn 10 bài/công ty
  python crawler.py --delay 3                 # Chờ 3 giây giữa các request
  python crawler.py --output results.json     # Đổi tên file output
        """,
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=DEFAULT_DELAY,
        help=f"Thời gian chờ giữa các request (giây, mặc định: {DEFAULT_DELAY})",
    )
    parser.add_argument(
        "--max-articles",
        type=int,
        default=DEFAULT_MAX_ARTICLES,
        help=f"Số bài tối đa mỗi công ty (mặc định: {DEFAULT_MAX_ARTICLES})",
    )
    parser.add_argument(
        "--company",
        type=str,
        default=None,
        help="Chỉ crawl công ty có tên chứa chuỗi này",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=DEFAULT_OUTPUT_FILE,
        help=f"Tên file JSON output (mặc định: {DEFAULT_OUTPUT_FILE})",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Thư mục output (mặc định: {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Xóa tiến trình cũ và crawl lại từ đầu",
    )

    args = parser.parse_args()

    # Reset nếu cần
    if args.reset:
        progress_path = os.path.join(args.output_dir, DEFAULT_PROGRESS_FILE)
        output_path = os.path.join(args.output_dir, args.output)
        for f in [progress_path, output_path]:
            if os.path.exists(f):
                os.remove(f)
                print(f"Đã xóa: {f}")

    # Lọc công ty nếu có --company
    companies = COMPANIES
    if args.company:
        companies = [
            c for c in COMPANIES if args.company.lower() in c.lower()
        ]
        if not companies:
            print(f"Không tìm thấy công ty nào chứa '{args.company}'")
            print("Gợi ý: kiểm tra lại tên trong file config.py")
            sys.exit(1)
        print(f"Tìm thấy {len(companies)} công ty khớp:")
        for c in companies:
            print(f"   - {c}")
        print()

    # Khởi tạo và chạy crawler
    crawler = NewsCrawler(
        companies=companies,
        delay=args.delay,
        max_articles=args.max_articles,
        output_dir=args.output_dir,
        output_file=args.output,
    )
    crawler.run()


if __name__ == "__main__":
    main()
