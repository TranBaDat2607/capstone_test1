"""
FPT News Crawler
"""

import asyncio
import html
import json
import logging
import random
import re
import shutil
import time
import unicodedata
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin, quote, urlparse

import httpx
from bs4 import BeautifulSoup

# Config
BASE_DIR = Path(__file__).resolve().parent
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("fpt_crawler")

REQUEST_DELAY_MIN = 0.5
REQUEST_DELAY_MAX = 1.5
MAX_RETRIES = 3
TIMEOUT = 20
MAX_PAGES_PER_KEYWORD = 3
MAX_ARTICLES_PER_SOURCE = 80
MIN_CONTENT_LENGTH = 100
MAX_CONCURRENT = 8  # Số request đồng thời tối đa

CRAWL_YEARS = list(range(2010, 2027))

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.1 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36 Edg/129.0.0.0",
]

SEARCH_KEYWORDS = [
    # Tập đoàn
    "FPT", "Tập đoàn FPT",
    # Công ty con trực tiếp
    "FPT Software", "FPT Telecom", "FPT IS", "FPT Information System",
    "FPT Education", "FPT Online", "FPT Investment",
    "FPT Smart Cloud", "FPT Digital",
    # Công ty con cấp 2
    "FPT Semiconductor", 
    "FPT University", "FPT Polytechnic", "FUNiX",
    "Đại học FPT", "Cao đẳng FPT",
    # Công ty liên kết
    "FPT Retail", "FPT Shop", "FPT Long Châu",
    "Synnex FPT", "FPT Securities", "FPT Capital",
    "FPT HOMA", "FPT Play", "F.Studio",
    # Nhân vật chủ chốt
    "Trương Gia Bình",
]

# Semaphore cho async
semaphore: asyncio.Semaphore | None = None


def _random_headers() -> dict:
    """Tạo headers giả lập browser thật, rotate User-Agent."""
    ua = random.choice(USER_AGENTS)
    return {
        "User-Agent": ua,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.7,en;q=0.5",
        "Accept-Encoding": "gzip, deflate, br",
        "DNT": "1",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
    }


def _random_delay():
    """Random delay giữa các request."""
    return random.uniform(REQUEST_DELAY_MIN, REQUEST_DELAY_MAX)


# TEXT CLEANING

def clean_text(s: str) -> str:
    """Decode HTML entities & normalize unicode."""
    if not s:
        return ""
    # Decode HTML entities: &#7912; → Ứ, &amp; → &, ...
    s = html.unescape(s)
    # Normalize unicode (NFC = composed form, chuẩn cho tiếng Việt)
    s = unicodedata.normalize("NFC", s)
    # Loại bỏ ký tự điều khiển thừa
    s = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', s)
    return s.strip()


# ASYNC HTTP CLIENT

async def safe_get(client: httpx.AsyncClient, url: str) -> httpx.Response | None:
    """GET với retry, exponential backoff, xử lý 429."""
    for attempt in range(MAX_RETRIES):
        try:
            async with semaphore:
                r = await client.get(
                    url, headers=_random_headers(),
                    timeout=TIMEOUT, follow_redirects=True,
                )
            if r.status_code == 429:
                wait = 2 ** (attempt + 1) + random.random()
                logger.warning(f"  429 Too Many Requests - chờ {wait:.1f}s")
                await asyncio.sleep(wait)
                continue
            r.raise_for_status()
            return r
        except (httpx.HTTPStatusError, httpx.RequestError) as e:
            if attempt < MAX_RETRIES - 1:
                await asyncio.sleep(_random_delay() * (attempt + 1))
            else:
                logger.debug(f"  Failed: {url[:60]}... - {e}")
    return None


def is_fpt_related(title: str, content: str) -> bool:
    text = (title + " " + content).lower()
    return any(m in text for m in [
        "fpt", "tập đoàn fpt",
        "fpt software", "fpt telecom", "fpt is",
        "fpt education", "fpt online", "fpt investment",
        "fpt smart cloud", "fpt digital",
        "fpt semiconductor", "fpt telecom international",
        "fpt japan", "fpt usa", "fpt korea",
        "fpt university", "fpt polytechnic", "funix",
        "đại học fpt", "cao đẳng fpt",
        "fpt retail", "fpt shop", "fpt long châu", "long châu",
        "synnex fpt", "fpt securities", "fpt capital",
        "fpt homa", "fpt play", "f.studio",
        "trương gia bình",
    ])


# DATE UTILITIES

def normalize_date(raw: str) -> str:
    if not raw:
        return ""
    s = raw.strip()
    m = re.match(r"^(\d{4}-\d{2}-\d{2})", s)
    if m:
        return m.group(1)
    m = re.search(r"(\d{1,2})[/\-](\d{1,2})[/\-](\d{4})", s)
    if m:
        return f"{m.group(3)}-{m.group(2).zfill(2)}-{m.group(1).zfill(2)}"
    m = re.match(r"^(\d{4}-\d{2})$", s)
    if m:
        return s + "-01"
    return s


def extract_year_from_url(url: str) -> str | None:
    m = re.search(r"-(\d{4})(\d{2})(\d{2})\d{6,}\.htm", url)
    if m:
        y = int(m.group(1))
        if 2005 <= y <= 2030:
            return str(y)
    m = re.search(r"185(\d{2})(\d{2})(\d{2})\d+\.htm", url)
    if m:
        return "20" + m.group(1)
    m = re.search(r"/(20[0-2]\d)/", url)
    if m:
        return m.group(1)
    return None


def get_year(date_str: str, url: str) -> str:
    norm = normalize_date(date_str)
    m = re.search(r"(20[0-2]\d)", norm)
    if m:
        return m.group(1)
    y = extract_year_from_url(url)
    if y:
        return y
    return str(datetime.now().year)


# METADATA EXTRACTION

def extract_metadata(html_str: str, url: str) -> dict:
    soup = BeautifulSoup(html_str, "lxml")
    title, date_str, author = "", "", ""

    # Meta tags
    og = soup.find("meta", property="og:title")
    if og and og.get("content"):
        t = clean_text(og["content"])
        if len(t) > 10:
            title = t

    pub = soup.find("meta", property="article:published_time")
    if pub and pub.get("content"):
        date_str = pub["content"].strip()

    au = soup.find("meta", attrs={"name": "author"})
    if au and au.get("content"):
        v = clean_text(au["content"])
        if v.lower() not in ("vnexpress", "tuoi tre online", "vietnamnet news",
                              "thanhnien.vn", "tuoitre.vn", "vietnamnet.vn"):
            author = v

    # LD+JSON
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
            if isinstance(data, list):
                data = data[0] if data else {}
            if not isinstance(data, dict):
                continue
            if not title and data.get("headline"):
                title = clean_text(str(data["headline"]))
            if not date_str and data.get("datePublished"):
                date_str = str(data["datePublished"]).strip()
            if not author:
                a = data.get("author", {})
                if isinstance(a, dict) and a.get("name"):
                    author = clean_text(a["name"])
                elif isinstance(a, list) and a and isinstance(a[0], dict):
                    author = clean_text(a[0].get("name", ""))
        except (json.JSONDecodeError, TypeError, AttributeError):
            pass

    # CSS selectors
    if not title:
        for sel in ["h1.title-detail", "h1.article-title", "h1.detail__title",
                     "h1.content-detail-title", "h1"]:
            tag = soup.select_one(sel)
            if tag and tag.get_text(strip=True):
                title = clean_text(tag.get_text(strip=True))
                break

    if not date_str:
        for sel in ["span.date", "div.date-time", "div.detail__time",
                     "div.bread-crumb-detail__time"]:
            tag = soup.select_one(sel)
            if tag:
                date_str = tag.get("datetime", "") or tag.get_text(strip=True)
                if date_str:
                    break
        if not date_str:
            time_tag = soup.find("time", attrs={"datetime": True})
            if time_tag:
                date_str = time_tag["datetime"]

    if not author:
        for sel in ["p.author_mail strong", "span.author",
                     ".author-info .author-name", "div.detail__author a",
                     "p.article-author strong"]:
            tag = soup.select_one(sel)
            if tag and tag.get_text(strip=True):
                author = clean_text(tag.get_text(strip=True))
                break

    # URL patterns
    if not date_str:
        m = re.search(r"-(\d{4})(\d{2})(\d{2})\d{6,}\.htm", url)
        if m:
            date_str = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
        else:
            m = re.search(r"185(\d{2})(\d{2})(\d{2})\d+\.htm", url)
            if m:
                date_str = f"20{m.group(1)}-{m.group(2)}-{m.group(3)}"

    # Thử newspaper4k cho metadata bị thiếu
    if not title or not author:
        try:
            from newspaper import Article
            art = Article(url, language="vi")
            art.download(input_html=html_str)
            art.parse()
            if not title and art.title and len(art.title) > 10:
                title = clean_text(art.title)
            if not author and art.authors:
                author = clean_text(art.authors[0])
        except Exception:
            pass

    return {"title": title, "date": date_str, "author": author}


# CONTENT EXTRACTION

def extract_content(html_str: str) -> str:
    # Phương pháp 1: trafilatura (tốt nhất cho text extraction)
    try:
        import trafilatura
        text = trafilatura.extract(
            html_str, include_comments=False, include_tables=False,
            favor_recall=True, deduplicate=True,
        )
        if text and len(text.strip()) >= MIN_CONTENT_LENGTH:
            return clean_text(text)
    except Exception:
        pass

    # Phương pháp 2: newspaper4k
    try:
        from newspaper import Article
        art = Article("", language="vi")
        art.download(input_html=html_str)
        art.parse()
        if art.text and len(art.text.strip()) >= MIN_CONTENT_LENGTH:
            return clean_text(art.text)
    except Exception:
        pass

    # Phương pháp 3: BeautifulSoup CSS selectors (fallback cuối)
    soup = BeautifulSoup(html_str, "lxml")
    for sel in ["article.fck_detail p.Normal", "div.detail__content p",
                 "div.singular-content p", "div.maincontent p",
                 "div.content-detail-body p", "article p"]:
        parts = [p.get_text(strip=True) for p in soup.select(sel)
                 if p.get_text(strip=True) and len(p.get_text(strip=True)) > 20]
        if parts:
            return clean_text("\n".join(parts))
    return ""


# ARTICLE EXTRACTION

def _detect_source(url: str) -> str:
    for k, v in {"vnexpress": "VnExpress", "tuoitre": "Tuổi Trẻ",
                  "thanhnien": "Thanh Niên", "vietnamnet": "VietnamNet"}.items():
        if k in url.lower():
            return v
    return "Unknown"


def build_article(url: str, html_str: str) -> dict | None:
    meta = extract_metadata(html_str, url)
    content = extract_content(html_str)
    if not content or len(content) < MIN_CONTENT_LENGTH:
        return None
    title = meta["title"]
    if not is_fpt_related(title, content):
        return None
    date_str = normalize_date(meta["date"])
    kw = [k for k in SEARCH_KEYWORDS if k.lower() in (title + " " + content).lower()]
    return {
        "title": title, "url": url, "source": _detect_source(url),
        "published_date": date_str, "author": meta["author"],
        "content": content,
        "summary": content[:200] + "..." if len(content) > 200 else content,
        "keywords_matched": kw, "crawled_at": datetime.now().isoformat(),
    }


async def fetch_and_build(client: httpx.AsyncClient, url: str) -> dict | None:
    resp = await safe_get(client, url)
    if not resp:
        return None
    return build_article(url, resp.text)


# SEARCH FUNCTIONS (ASYNC)

async def search_vnexpress(client: httpx.AsyncClient, keyword: str, year: int = None) -> list[str]:
    urls = []
    for pg in range(1, MAX_PAGES_PER_KEYWORD + 1):
        params = f"q={quote(keyword)}&page={pg}"
        if year:
            t1 = int(datetime(year, 1, 1).timestamp())
            t2 = int(datetime(year, 12, 31, 23, 59, 59).timestamp())
            params += f"&fromdate={t1}&todate={t2}"
        r = await safe_get(client, f"https://timkiem.vnexpress.net/?{params}")
        if not r:
            break
        soup = BeautifulSoup(r.text, "lxml")
        found = 0
        for a in soup.select("article.item-news h3.title-news a[href], h3.title-news a[href]"):
            href = a.get("href", "")
            if href and "vnexpress.net" in href and href not in urls:
                urls.append(href)
                found += 1
        if found == 0:
            break
        await asyncio.sleep(_random_delay())
    return urls


async def search_tuoitre(client: httpx.AsyncClient, keyword: str) -> list[str]:
    urls = []
    for pg in range(1, MAX_PAGES_PER_KEYWORD + 1):
        r = await safe_get(client, f"https://tuoitre.vn/tim-kiem.htm?keywords={quote(keyword)}&page={pg}")
        if not r:
            break
        soup = BeautifulSoup(r.text, "lxml")
        found = 0
        for a in soup.select("h3 a[href], .news-item a[href]"):
            href = a.get("href", "")
            if not href:
                continue
            full = urljoin("https://tuoitre.vn", href)
            if "tuoitre.vn" in full and ".htm" in full and full not in urls:
                urls.append(full)
                found += 1
        if found == 0:
            break
        await asyncio.sleep(_random_delay())
    return urls


async def search_vietnamnet(client: httpx.AsyncClient, keyword: str) -> list[str]:
    urls = []
    for pg in range(1, 6):
        r = await safe_get(client, f"https://vietnamnet.vn/tim-kiem?q={quote(keyword)}&page={pg}")
        if not r:
            break
        soup = BeautifulSoup(r.text, "lxml")
        found = 0
        for a in soup.select("h3 a[href], h3.horizontalPost__main-title a[href]"):
            href = a.get("href", "")
            if not href:
                continue
            full = urljoin("https://vietnamnet.vn", href)
            if "vietnamnet.vn" in full and full not in urls:
                urls.append(full)
                found += 1
        if found == 0:
            break
        await asyncio.sleep(_random_delay())
    return urls


def search_thanhnien_pw(keyword: str, browser=None) -> list[str]:
    """Search Thanh Niên dùng Playwright (domcontentloaded — rất nhanh)."""
    urls = []
    if not browser:
        return urls
    try:
        ctx = browser.new_context(
            user_agent=random.choice(USER_AGENTS), locale="vi-VN",
        )
        page = ctx.new_page()
        for pg in range(1, MAX_PAGES_PER_KEYWORD + 1):
            try:
                page.goto(
                    f"https://thanhnien.vn/tim-kiem?q={quote(keyword)}&page={pg}",
                    wait_until="domcontentloaded", timeout=15000,
                )
                page.wait_for_timeout(1500)
            except Exception:
                break
            soup = BeautifulSoup(page.content(), "lxml")
            found = 0
            for a in soup.select("h3 a[href], h2 a[href], a.story__title[href]"):
                href = a.get("href", "")
                if not href:
                    continue
                full = urljoin("https://thanhnien.vn", href)
                if "thanhnien.vn" in full and ".htm" in full and full not in urls:
                    urls.append(full)
                    found += 1
            if found == 0:
                break
            time.sleep(random.uniform(REQUEST_DELAY_MIN, REQUEST_DELAY_MAX))
        ctx.close()
    except Exception as e:
        logger.warning(f"  Thanh Niên search error: {e}")
    return urls


async def search_google_site(client: httpx.AsyncClient, site_domain: str,
                              keyword: str, year: int) -> list[str]:
    """Dùng Google Search để tìm bài cũ trên 1 domain cụ thể."""
    urls = []
    query = quote(f'site:{site_domain} "{keyword}" {year}')
    google_url = f"https://www.google.com/search?q={query}&num=20&hl=vi"
    try:
        r = await safe_get(client, google_url)
        if r and r.status_code == 200:
            soup = BeautifulSoup(r.text, "lxml")
            for a in soup.find_all("a", href=True):
                href = a["href"]
                m = re.search(r"/url\?q=(https?://[^&]+)", href)
                if m:
                    real_url = m.group(1)
                    if site_domain in real_url and real_url not in urls:
                        urls.append(real_url)
                elif site_domain in href and href.startswith("http") and href not in urls:
                    urls.append(href)
    except Exception:
        pass
    return urls


# FILE SAVE

def save_article(article: dict, year: str, source_key: str) -> Path:
    year_dir = BASE_DIR / year
    year_dir.mkdir(parents=True, exist_ok=True)
    existing = sorted(year_dir.glob(f"{source_key}_*.json"))
    if existing:
        m = re.search(r"_(\d+)$", existing[-1].stem)
        next_num = int(m.group(1)) + 1 if m else 1
    else:
        next_num = 1
    filepath = year_dir / f"{source_key}_{next_num:03d}.json"
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(article, f, ensure_ascii=False, indent=2)
    return filepath


# CRAWL LOGIC (ASYNC)

async def crawl_batch(client: httpx.AsyncClient, urls: list[str],
                       source_key: str, stats: dict):
    """Crawl 1 batch URLs song song."""
    tasks = [fetch_and_build(client, url) for url in urls]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    for url, result in zip(urls, results):
        if isinstance(result, Exception):
            logger.debug(f"  Exception: {url[:60]}... - {result}")
            stats["failed"] += 1
            continue
        if result is None:
            stats["failed"] += 1
            continue
        article = result
        year = get_year(article["published_date"], url)
        fp = save_article(article, year, source_key)
        logger.info(f"    {year}/{fp.name} | {article['title'][:50]} | {article['published_date']}")
        stats["success"] += 1
        stats["by_year"][year] = stats["by_year"].get(year, 0) + 1


async def crawl_with_httpx(client: httpx.AsyncClient, source_key: str, name: str,
                            search_fn, use_year: bool = False,
                            use_google_old: bool = False) -> dict:
    """Crawl nguồn báo dùng httpx async."""
    logger.info(f"\n{'='*60}")
    logger.info(f"   {name}")
    logger.info(f"{'='*60}")

    all_urls = set()

    # Search nội bộ
    if use_year:
        for year in CRAWL_YEARS:
            for kw in SEARCH_KEYWORDS:
                logger.info(f"   \"{kw}\" năm {year}")
                found = await search_fn(client, kw, year=year)
                logger.info(f"     Found {len(found)} URL")
                all_urls.update(found)
                await asyncio.sleep(_random_delay())
    else:
        for kw in SEARCH_KEYWORDS:
            logger.info(f"   \"{kw}\"")
            found = await search_fn(client, kw)
            logger.info(f"     Found {len(found)} URL")
            all_urls.update(found)
            await asyncio.sleep(_random_delay())

    # Google Search bổ sung cho năm cũ (2010-2019)
    if use_google_old:
        domain = {"vnexpress": "vnexpress.net", "tuoitre": "tuoitre.vn",
                  "vietnamnet": "vietnamnet.vn"}.get(source_key)
        if domain:
            for year in range(2010, 2020):
                for kw in ["FPT", "FPT Software"]:
                    logger.info(f"   Google: \"{kw}\" {year} site:{domain}")
                    found = await search_google_site(client, domain, kw, year)
                    before = len(all_urls)
                    all_urls.update(found)
                    logger.info(f"     Added +{len(all_urls) - before} URL mới")
                    await asyncio.sleep(2.0 + random.random())  # Google rate limit

    url_list = list(all_urls)[:MAX_ARTICLES_PER_SOURCE]
    logger.info(f"   Tổng: {len(all_urls)} unique -> crawl {len(url_list)}")

    stats = {"total": len(url_list), "success": 0, "failed": 0, "skipped": 0, "by_year": {}}

    # Crawl song song theo batch
    batch_size = MAX_CONCURRENT
    for i in range(0, len(url_list), batch_size):
        batch = url_list[i:i + batch_size]
        logger.info(f"   Batch {i // batch_size + 1}/{(len(url_list) + batch_size - 1) // batch_size} - {len(batch)} URLs")
        await crawl_batch(client, batch, source_key, stats)
        await asyncio.sleep(_random_delay())

    return stats


async def crawl_thanhnien(client: httpx.AsyncClient) -> dict:
    """Crawl Thanh Niên: Playwright search + httpx async extract."""
    logger.info(f"\n{'='*60}")
    logger.info(f"   Thanh Niên")
    logger.info(f"{'='*60}")

    stats = {"total": 0, "success": 0, "failed": 0, "skipped": 0, "by_year": {}}

    all_urls = set()
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            for kw in SEARCH_KEYWORDS:
                logger.info(f"   \"{kw}\"")
                found = search_thanhnien_pw(kw, browser=browser)
                logger.info(f"     Found {len(found)} URL")
                all_urls.update(found)

            # Google bổ sung bài cũ
            for year in range(2010, 2020):
                for kw in ["FPT", "FPT Software"]:
                    logger.info(f"   Google: \"{kw}\" {year} site:thanhnien.vn")
                    found = await search_google_site(client, "thanhnien.vn", kw, year)
                    before = len(all_urls)
                    all_urls.update(found)
                    logger.info(f"     Added +{len(all_urls) - before} URL mới")
                    await asyncio.sleep(2.0 + random.random())

            browser.close()
    except ImportError:
        logger.error("   playwright not installed")
        return stats

    url_list = list(all_urls)[:MAX_ARTICLES_PER_SOURCE]
    stats["total"] = len(url_list)
    logger.info(f"   Tổng: {len(all_urls)} unique -> crawl {len(url_list)}")

    # Extract bằng httpx async (song song)
    batch_size = MAX_CONCURRENT
    for i in range(0, len(url_list), batch_size):
        batch = url_list[i:i + batch_size]
        logger.info(f"   Batch {i // batch_size + 1}/{(len(url_list) + batch_size - 1) // batch_size} - {len(batch)} URLs")
        await crawl_batch(client, batch, "thanhnien", stats)
        await asyncio.sleep(_random_delay())

    return stats


# MAIN

def clean_old_data():
    for item in BASE_DIR.iterdir():
        if item.is_dir() and re.match(r"^20\d{2}$", item.name):
            shutil.rmtree(item)
            logger.info(f"  Xóa: {item.name}/")
    s = BASE_DIR / "crawl_summary.json"
    if s.exists():
        s.unlink()


async def main():
    global semaphore
    semaphore = asyncio.Semaphore(MAX_CONCURRENT)

    logger.info("=" * 60)
    logger.info("  FPT NEWS CRAWLER v6")
    logger.info(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info(f"  Năm: {CRAWL_YEARS[0]}–{CRAWL_YEARS[-1]}")
    logger.info(f"  Async: {MAX_CONCURRENT} concurrent requests")
    logger.info("=" * 60)

    logger.info("\n  Dọn dẹp dữ liệu cũ...")
    clean_old_data()

    total_stats = {"sources": {}, "total_articles": 0}

    async with httpx.AsyncClient(http2=True, verify=True) as client:

        # VnExpress - year filter + Google bổ sung bài cũ
        try:
            s = await crawl_with_httpx(client, "vnexpress", "VnExpress",
                                        search_vnexpress, use_year=True, use_google_old=True)
            total_stats["sources"]["vnexpress"] = s
            total_stats["total_articles"] += s["success"]
        except Exception as e:
            logger.error(f"   VnExpress: {e}")
            total_stats["sources"]["vnexpress"] = {"error": str(e)}

        # Tuổi Trẻ + Google bổ sung
        try:
            s = await crawl_with_httpx(client, "tuoitre", "Tuổi Trẻ",
                                        search_tuoitre, use_year=False, use_google_old=True)
            total_stats["sources"]["tuoitre"] = s
            total_stats["total_articles"] += s["success"]
        except Exception as e:
            logger.error(f"   Tuổi Trẻ: {e}")
            total_stats["sources"]["tuoitre"] = {"error": str(e)}

        # Thanh Niên - Playwright search + httpx extract + Google bổ sung
        try:
            s = await crawl_thanhnien(client)
            total_stats["sources"]["thanhnien"] = s
            total_stats["total_articles"] += s["success"]
        except Exception as e:
            logger.error(f"   Thanh Niên: {e}")
            total_stats["sources"]["thanhnien"] = {"error": str(e)}

        # VietnamNet + Google bổ sung
        try:
            s = await crawl_with_httpx(client, "vietnamnet", "VietnamNet",
                                        search_vietnamnet, use_year=False, use_google_old=True)
            total_stats["sources"]["vietnamnet"] = s
            total_stats["total_articles"] += s["success"]
        except Exception as e:
            logger.error(f"   VietnamNet: {e}")
            total_stats["sources"]["vietnamnet"] = {"error": str(e)}

    # Summary
    logger.info("\n" + "=" * 60)
    logger.info("   KẾT QUẢ")
    logger.info("=" * 60)
    logger.info(f"  Tổng: {total_stats['total_articles']} bài")

    all_years = {}
    for sk, st in total_stats["sources"].items():
        if "error" in st:
            logger.info(f"  {sk}: {st['error']}")
        else:
            logger.info(f"  {sk}: Success: {st['success']} Failed: {st['failed']}")
            for y, c in sorted(st.get("by_year", {}).items()):
                logger.info(f"    └── {y}: {c}")
                all_years[y] = all_years.get(y, 0) + c

    logger.info("\n  Phân bổ năm:")
    for y in sorted(all_years):
        logger.info(f"    {y}: {all_years[y]} bài")

    with open(BASE_DIR / "crawl_summary.json", "w", encoding="utf-8") as f:
        json.dump(total_stats, f, ensure_ascii=False, indent=2)

    logger.info("   DONE!")


if __name__ == "__main__":
    asyncio.run(main())
