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
import hashlib
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin, quote, urlparse

import httpx
from bs4 import BeautifulSoup

BASE_DIR = Path(__file__).resolve().parent.parent / "data" / "raw" / "crawl_data_news"
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("fpt_crawler")

REQUEST_DELAY_MIN = 0.5
REQUEST_DELAY_MAX = 1.5
MAX_RETRIES = 3
TIMEOUT = 20
MAX_PAGES_PER_KEYWORD = 3
MAX_ARTICLES_PER_SOURCE = 80
MIN_CONTENT_LENGTH = 100
MAX_CONCURRENT = 8

CRAWL_YEARS = list(range(2010, 2027))
IS_TEST_MODE = False

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
    "FPT", "Tập đoàn FPT",
    "FPT Software", "FPT Telecom", "FPT IS", "FPT Information System",
    "FPT Education", "FPT Online", "FPT Investment",
    "FPT Smart Cloud", "FPT Digital",
    "FPT Semiconductor", 
    "FPT University", "FPT Polytechnic", "FUNiX",
    "Đại học FPT", "Cao đẳng FPT",
    "FPT Retail", "FPT Shop", "FPT Long Châu",
    "Synnex FPT", "FPT Securities", "FPT Capital",
    "FPT HOMA", "FPT Play", "F.Studio",
    "Trương Gia Bình",
]

cpu_executor = ThreadPoolExecutor(max_workers=4)

article_counters = {}
article_counters_lock = threading.Lock()

google_blocked = False
google_blocked_lock = threading.Lock()

def normalize_url(url: str) -> str:
    """Chuẩn hóa URL để loại bỏ query params thừa, hash tags, vv."""
    if not url:
        return ""
    parsed = urlparse(url)
    path = parsed.path
    if parsed.netloc.endswith("vnexpress.net") or parsed.netloc.endswith("tuoitre.vn") or parsed.netloc.endswith("vietnamnet.vn") or parsed.netloc.endswith("thanhnien.vn"):
        query = ""
    else:
        query = parsed.query
    return f"{parsed.scheme}://{parsed.netloc}{path}{'?' + query if query else ''}"

class DomainRateLimiter:
    def __init__(self):
        self.limits = {
            "vnexpress.net": 3,
            "tuoitre.vn": 2,
            "thanhnien.vn": 2,
            "vietnamnet.vn": 2,
            "google.com": 1,
        }
        self.delays = {
            "vnexpress.net": 0.8,
            "tuoitre.vn": 1.0,
            "thanhnien.vn": 1.0,
            "vietnamnet.vn": 1.0,
            "google.com": 3.0,
        }
        self.semaphores = {}
        self.last_request_time = {}
        self.lock = asyncio.Lock()

    def get_domain(self, url: str) -> str:
        parsed = urlparse(url)
        dom = parsed.netloc.lower()
        if dom.startswith("www."):
            dom = dom[4:]
        return dom

    async def throttle(self, dom: str):
        async with self.lock:
            now = time.time()
            elapsed = now - self.last_request_time.get(dom, 0.0)
            delay = self.delays.get(dom, 1.5)
            wait_time = delay - elapsed
            if wait_time > 0:
                await asyncio.sleep(wait_time)
            self.last_request_time[dom] = time.time()

    async def acquire(self, url: str):
        dom = self.get_domain(url)
        async with self.lock:
            if dom not in self.semaphores:
                limit = self.limits.get(dom, 2)
                self.semaphores[dom] = asyncio.Semaphore(limit)
        await self.semaphores[dom].acquire()
        await self.throttle(dom)

    def release(self, url: str):
        dom = self.get_domain(url)
        if dom in self.semaphores:
            try:
                self.semaphores[dom].release()
            except ValueError:
                pass

class DomainLimiterContext:
    def __init__(self, limiter: DomainRateLimiter, url: str):
        self.limiter = limiter
        self.url = url
    async def __aenter__(self):
        await self.limiter.acquire(self.url)
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        self.limiter.release(self.url)

class ResponseCache:
    def __init__(self, cache_dir: Path, use_cache: bool = True):
        self.cache_dir = cache_dir / ".cache"
        self.use_cache = use_cache
        if self.use_cache:
            self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _get_path(self, url: str) -> Path:
        h = hashlib.sha1(url.encode("utf-8")).hexdigest()
        return self.cache_dir / f"{h}.json"

    def get(self, url: str, max_age_seconds: float) -> tuple[str, int] | None:
        if not self.use_cache:
            return None
        path = self._get_path(url)
        if path.exists():
            try:
                mtime = path.stat().st_mtime
                if time.time() - mtime < max_age_seconds:
                    with open(path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    return data.get("text"), data.get("status_code", 200)
            except Exception:
                pass
        return None

    def set(self, url: str, text: str, status_code: int):
        if not self.use_cache:
            return
        path = self._get_path(url)
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"text": text, "status_code": status_code, "url": url}, f, ensure_ascii=False)
        except Exception:
            pass

class ContentValidator:
    @staticmethod
    def quick_check(html_str: str) -> tuple[bool, str]:
        if not html_str or len(html_str) < 500:
            return False, "Page too small or empty"
        
        html_lower = html_str.lower()
        
        title_match = re.search(r"<title>(.*?)</title>", html_lower)
        if title_match:
            title_text = title_match.group(1).strip()
            title_captcha_patterns = [
                "captcha", "cloudflare", "just a moment", "security check", 
                "attention required", "robot verification", "human verification",
                "robot check"
            ]
            for pattern in title_captcha_patterns:
                if pattern in title_text:
                    return False, f"Title indicates captcha/block: {title_text}"

        error_patterns = [
            r"<title>403 forbidden", r"<title>404 not found", 
            r"<title>502 bad gateway", r"<title>503 service temporarily unavailable",
            r"<title>504 gateway time-out", r"<title>500 internal server error"
        ]
        for pattern in error_patterns:
            if re.search(pattern, html_lower):
                return False, f"Server error page detected: {pattern}"
                
        return True, ""

class CrawlMetrics:
    def __init__(self):
        self.lock = threading.Lock()
        self.start_time = time.time()
        self.success = 0
        self.failed = 0
        self.skipped = 0
        self.retries = 0
        self.rate_limits = 0
        self.latencies = []
        self.domain_stats = {}

    def record_request(self, url: str, status_code: int, latency: float, is_retry: bool = False, is_rate_limit: bool = False):
        parsed = urlparse(url)
        dom = parsed.netloc.lower()
        if dom.startswith("www."):
            dom = dom[4:]
        with self.lock:
            if dom not in self.domain_stats:
                self.domain_stats[dom] = {"success": 0, "failed": 0, "rate_limits": 0}
            if status_code == 200:
                self.success += 1
                self.domain_stats[dom]["success"] += 1
            else:
                self.failed += 1
                self.domain_stats[dom]["failed"] += 1
            if is_retry:
                self.retries += 1
            if is_rate_limit:
                self.rate_limits += 1
                self.domain_stats[dom]["rate_limits"] += 1
            self.latencies.append(latency)

    def record_skip(self):
        with self.lock:
            self.skipped += 1

    def log_progress(self):
        with self.lock:
            elapsed = time.time() - self.start_time
            avg_latency = sum(self.latencies) / len(self.latencies) if self.latencies else 0.0
            pages_per_sec = (self.success + self.failed) / elapsed if elapsed > 0 else 0.0
            logger.info(
                f"[Metrics] Elapsed: {elapsed:.1f}s | Success: {self.success} | "
                f"Failed: {self.failed} | Skipped: {self.skipped} | "
                f"Retries: {self.retries} | Rate limits: {self.rate_limits} | "
                f"Speed: {pages_per_sec:.2f} pages/sec | Avg Latency: {avg_latency:.2f}s"
            )

limiter = DomainRateLimiter()
cache = ResponseCache(BASE_DIR)
metrics = CrawlMetrics()

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

def clean_text(s: str) -> str:
    """Decode HTML entities & normalize unicode."""
    if not s:
        return ""
    s = html.unescape(s)
    s = unicodedata.normalize("NFC", s)
    s = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', s)
    return s.strip()

async def safe_get(client: httpx.AsyncClient, url: str, cache_ttl: float = 604800.0) -> httpx.Response | None:
    """GET với retry, exponential backoff, xử lý 429, cache, rate limit và validation."""
    cached_val = cache.get(url, cache_ttl)
    if cached_val is not None:
        cached_text, status_code = cached_val
        metrics.record_skip()
        return httpx.Response(
            status_code=status_code,
            content=cached_text.encode("utf-8"),
            request=httpx.Request("GET", url)
        )

    for attempt in range(MAX_RETRIES):
        start_time = time.time()
        try:
            async with DomainLimiterContext(limiter, url):
                r = await client.get(
                    url, headers=_random_headers(),
                    timeout=TIMEOUT, follow_redirects=True,
                )
            
            latency = time.time() - start_time
            
            if r.status_code == 429 or r.status_code == 503:
                retry_after = r.headers.get("Retry-After")
                if retry_after and retry_after.isdigit():
                    wait = int(retry_after) + random.random()
                else:
                    wait = 2 ** (attempt + 1) + random.random()
                logger.warning(f"  Rate Limit ({r.status_code}) - chờ {wait:.1f}s: {url[:60]}")
                metrics.record_request(url, r.status_code, latency, is_retry=(attempt > 0), is_rate_limit=True)
                await asyncio.sleep(wait)
                continue
            
            if r.status_code in (404, 410, 451):
                logger.debug(f"  Permanent failure ({r.status_code}): {url}")
                metrics.record_request(url, r.status_code, latency, is_retry=(attempt > 0))
                cache.set(url, r.text, r.status_code)
                return r
                
            r.raise_for_status()
            
            if "text/html" in r.headers.get("content-type", ""):
                is_valid, reason = ContentValidator.quick_check(r.text)
                if not is_valid:
                    logger.warning(f"  Content validation failed for {url[:60]}...: {reason}")
                    metrics.record_request(url, r.status_code, latency, is_retry=(attempt > 0))
                    return None
            
            cache.set(url, r.text, r.status_code)
            metrics.record_request(url, r.status_code, latency, is_retry=(attempt > 0))
            return r

        except (httpx.HTTPStatusError, httpx.RequestError) as e:
            latency = time.time() - start_time
            status_code = e.response.status_code if hasattr(e, "response") and e.response else 500
            metrics.record_request(url, status_code, latency, is_retry=(attempt > 0))
            
            if hasattr(e, "response") and e.response and e.response.status_code in (400, 401, 403):
                logger.debug(f"  Client error ({e.response.status_code}) - no retry: {url[:60]}...")
                return None
                
            if attempt < MAX_RETRIES - 1:
                wait_time = _random_delay() * (attempt + 1)
                await asyncio.sleep(wait_time)
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


def extract_metadata(html_str: str, url: str) -> dict:
    soup = BeautifulSoup(html_str, "lxml")
    title, date_str, author = "", "", ""

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

    if not date_str:
        m = re.search(r"-(\d{4})(\d{2})(\d{2})\d{6,}\.htm", url)
        if m:
            date_str = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
        else:
            m = re.search(r"185(\d{2})(\d{2})(\d{2})\d+\.htm", url)
            if m:
                date_str = f"20{m.group(1)}-{m.group(2)}-{m.group(3)}"

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


def extract_content(html_str: str) -> str:
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

    try:
        from newspaper import Article
        art = Article("", language="vi")
        art.download(input_html=html_str)
        art.parse()
        if art.text and len(art.text.strip()) >= MIN_CONTENT_LENGTH:
            return clean_text(art.text)
    except Exception:
        pass

    soup = BeautifulSoup(html_str, "lxml")
    for sel in ["article.fck_detail p.Normal", "div.detail__content p",
                 "div.singular-content p", "div.maincontent p",
                 "div.content-detail-body p", "article p"]:
        parts = [p.get_text(strip=True) for p in soup.select(sel)
                 if p.get_text(strip=True) and len(p.get_text(strip=True)) > 20]
        if parts:
            return clean_text("\n".join(parts))
    return ""


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


def fetch_with_playwright_in_thread(url: str) -> str | None:
    """Fetch HTML of a page using Playwright sync to bypass hCaptcha/Cloudflare."""
    from playwright.sync_api import sync_playwright
    logger.info(f"  [Playwright Fallback] Fetching url: {url}")
    html_content = None
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            ctx = browser.new_context(
                user_agent=random.choice(USER_AGENTS),
                locale="vi-VN",
                viewport={"width": 1280, "height": 800}
            )
            page = ctx.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=15000)
            page.wait_for_timeout(2000)
            html_content = page.content()
            ctx.close()
            browser.close()
    except Exception as e:
        logger.warning(f"  [Playwright Fallback] Error fetching {url[:60]}: {e}")
    return html_content


async def fetch_and_build(client: httpx.AsyncClient, url: str) -> dict | None:
    resp = await safe_get(client, url)
    loop = asyncio.get_running_loop()
    if resp:
        article = await loop.run_in_executor(cpu_executor, build_article, url, resp.text)
        if article:
            return article

    if "thanhnien.vn" in url or "tuoitre.vn" in url or "vietnamnet.vn" in url:
        logger.info(f"  [Fallback Triggered] Retrying with Playwright for {url[:60]}...")
        html_str = await loop.run_in_executor(cpu_executor, fetch_with_playwright_in_thread, url)
        if html_str:
            is_valid, reason = ContentValidator.quick_check(html_str)
            if is_valid:
                article = await loop.run_in_executor(cpu_executor, build_article, url, html_str)
                return article
            else:
                logger.warning(f"  Playwright content validation failed: {reason}")
    return None


async def search_vnexpress(client: httpx.AsyncClient, keyword: str, year: int = None) -> list[str]:
    urls = []
    for pg in range(1, MAX_PAGES_PER_KEYWORD + 1):
        params = f"q={quote(keyword)}&page={pg}"
        if year:
            t1 = int(datetime(year, 1, 1).timestamp())
            t2 = int(datetime(year, 12, 31, 23, 59, 59).timestamp())
            params += f"&fromdate={t1}&todate={t2}"
        r = await safe_get(client, f"https://timkiem.vnexpress.net/?{params}", cache_ttl=86400.0)
        if not r:
            break
        soup = BeautifulSoup(r.text, "lxml")
        found = 0
        for a in soup.select("article.item-news h3.title-news a[href], h3.title-news a[href]"):
            href = a.get("href", "")
            normalized = normalize_url(href)
            if normalized and "vnexpress.net" in normalized and normalized not in urls:
                urls.append(normalized)
                found += 1
        if found == 0:
            break
        await asyncio.sleep(_random_delay())
    return urls


async def search_tuoitre(client: httpx.AsyncClient, keyword: str) -> list[str]:
    urls = []
    for pg in range(1, MAX_PAGES_PER_KEYWORD + 1):
        r = await safe_get(client, f"https://tuoitre.vn/tim-kiem.htm?keywords={quote(keyword)}&page={pg}", cache_ttl=86400.0)
        if not r:
            break
        soup = BeautifulSoup(r.text, "lxml")
        found = 0
        for a in soup.select("h3 a[href], .news-item a[href]"):
            href = a.get("href", "")
            if not href:
                continue
            full = urljoin("https://tuoitre.vn", href)
            normalized = normalize_url(full)
            if "tuoitre.vn" in normalized and ".htm" in normalized and normalized not in urls:
                urls.append(normalized)
                found += 1
        if found == 0:
            break
        await asyncio.sleep(_random_delay())
    return urls


async def search_vietnamnet(client: httpx.AsyncClient, keyword: str) -> list[str]:
    urls = []
    for pg in range(1, 6):
        r = await safe_get(client, f"https://vietnamnet.vn/tim-kiem?q={quote(keyword)}&page={pg}", cache_ttl=86400.0)
        if not r:
            break
        soup = BeautifulSoup(r.text, "lxml")
        found = 0
        for a in soup.select("h3 a[href], h3.horizontalPost__main-title a[href]"):
            href = a.get("href", "")
            if not href:
                continue
            full = urljoin("https://vietnamnet.vn", href)
            normalized = normalize_url(full)
            if "vietnamnet.vn" in normalized and normalized not in urls:
                urls.append(normalized)
                found += 1
        if found == 0:
            break
        await asyncio.sleep(_random_delay())
    return urls


def run_all_thanhnien_search_in_thread(keywords: list[str]) -> list[str]:
    """Search Thanh Niên dùng Playwright (sync) chạy trong thread pool riêng để không block event loop."""
    from playwright.sync_api import sync_playwright
    all_urls = set()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            ctx = browser.new_context(
                user_agent=random.choice(USER_AGENTS), locale="vi-VN",
            )
            page = ctx.new_page()
            for kw in keywords:
                for pg in range(1, MAX_PAGES_PER_KEYWORD + 1):
                    try:
                        page.goto(
                            f"https://thanhnien.vn/tim-kiem?q={quote(kw)}&page={pg}",
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
                        normalized = normalize_url(full)
                        if "thanhnien.vn" in normalized and ".htm" in normalized and normalized not in all_urls:
                            all_urls.add(normalized)
                            found += 1
                    if found == 0:
                        break
                    time.sleep(random.uniform(REQUEST_DELAY_MIN, REQUEST_DELAY_MAX))
            ctx.close()
            browser.close()
    except Exception as e:
        logger.warning(f"  Thanh Niên search error: {e}")
    return list(all_urls)


def run_tuoitre_search_in_thread(keywords: list[str]) -> list[str]:
    """Search Tuổi Trẻ dùng Playwright (sync) chạy trong thread pool riêng."""
    from playwright.sync_api import sync_playwright
    all_urls = set()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            ctx = browser.new_context(
                user_agent=random.choice(USER_AGENTS), locale="vi-VN",
            )
            page = ctx.new_page()
            for kw in keywords:
                for pg in range(1, MAX_PAGES_PER_KEYWORD + 1):
                    try:
                        url = f"https://tuoitre.vn/tim-kiem.htm?keywords={quote(kw)}&page={pg}"
                        page.goto(url, wait_until="domcontentloaded", timeout=20000)
                        page.wait_for_timeout(2000)
                    except Exception as e:
                        logger.warning(f"  [Playwright] Tuổi Trẻ search error navigating to {kw} page {pg}: {e}")
                        break
                    soup = BeautifulSoup(page.content(), "lxml")
                    found = 0
                    for a in soup.select("h3 a[href], .news-item a[href]"):
                        href = a.get("href", "")
                        if not href:
                            continue
                        full = urljoin("https://tuoitre.vn", href)
                        normalized = normalize_url(full)
                        if "tuoitre.vn" in normalized and ".htm" in normalized and normalized not in all_urls:
                            all_urls.add(normalized)
                            found += 1
                    if found == 0:
                        break
                    time.sleep(random.uniform(REQUEST_DELAY_MIN, REQUEST_DELAY_MAX))
            ctx.close()
            browser.close()
    except Exception as e:
        logger.warning(f"  Tuổi Trẻ Playwright search error: {e}")
    return list(all_urls)


def run_vietnamnet_search_in_thread(keywords: list[str]) -> list[str]:
    """Search VietnamNet dùng Playwright (sync) chạy trong thread pool."""
    from playwright.sync_api import sync_playwright
    all_urls = set()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            ctx = browser.new_context(
                user_agent=random.choice(USER_AGENTS), locale="vi-VN",
            )
            page = ctx.new_page()
            for kw in keywords:
                for pg in range(1, MAX_PAGES_PER_KEYWORD + 1):
                    try:
                        url = f"https://vietnamnet.vn/tim-kiem?q={quote(kw)}&page={pg}"
                        page.goto(url, wait_until="domcontentloaded", timeout=20000)
                        try:
                            page.wait_for_selector(".horizontalPost, .verticalPost, h3", timeout=10000)
                        except Exception:
                            pass
                        page.wait_for_timeout(2000)
                    except Exception as e:
                        logger.warning(f"  [Playwright] VietnamNet search timeout/error for {kw} page {pg}: {e}")
                        break
                    soup = BeautifulSoup(page.content(), "lxml")
                    found = 0
                    for a in soup.select("h3 a[href], h3.horizontalPost__main-title a[href], .horizontalPost a[href], .verticalPost a[href]"):
                        href = a.get("href", "")
                        if not href:
                            continue
                        full = urljoin("https://vietnamnet.vn", href)
                        normalized = normalize_url(full)
                        if "vietnamnet.vn" in normalized and normalized not in all_urls:
                            all_urls.add(normalized)
                            found += 1
                    if found == 0:
                        break
                    time.sleep(random.uniform(REQUEST_DELAY_MIN, REQUEST_DELAY_MAX))
            ctx.close()
            browser.close()
    except Exception as e:
        logger.warning(f"  VietnamNet Playwright search error: {e}")
    return list(all_urls)


async def search_vietnamnet_rss(client: httpx.AsyncClient) -> list[str]:
    """Lấy các bài viết mới nhất từ RSS của VietnamNet."""
    urls = []
    rss_feeds = [
        "https://vietnamnet.vn/rss/tin-moi-nhat.rss",
        "https://vietnamnet.vn/rss/kinh-doanh.rss",
        "https://vietnamnet.vn/rss/cong-nghe.rss",
        "https://vietnamnet.vn/rss/thoi-su.rss",
    ]
    for feed in rss_feeds:
        try:
            r = await safe_get(client, feed, cache_ttl=3600.0)
            if r and r.status_code == 200:
                soup = BeautifulSoup(r.text, "lxml")
                for item in soup.find_all("item"):
                    link = item.find("link")
                    if link and link.text:
                        normalized = normalize_url(link.text.strip())
                        if "vietnamnet.vn" in normalized and normalized not in urls:
                            urls.append(normalized)
        except Exception as e:
            logger.warning(f"  Error reading RSS feed {feed}: {e}")
    return urls


async def search_google_site(client: httpx.AsyncClient, site_domain: str,
                              keyword: str, year: int) -> list[str]:
    """Dùng Google Search để tìm bài cũ trên 1 domain cụ thể."""
    global google_blocked
    if google_blocked:
        return []
    urls = []
    query = quote(f'site:{site_domain} "{keyword}" {year}')
    google_url = f"https://www.google.com/search?q={query}&num=20&hl=vi"
    try:
        r = await safe_get(client, google_url, cache_ttl=86400.0)
        if r:
            if r.status_code == 429:
                with google_blocked_lock:
                    google_blocked = True
                logger.warning("  [Google Search] Google returned 429. Disabling Google Search for the rest of this run.")
                return []
            if r.status_code == 200:
                soup = BeautifulSoup(r.text, "lxml")
                for a in soup.find_all("a", href=True):
                    href = a["href"]
                    m = re.search(r"/url\?q=(https?://[^&]+)", href)
                    if m:
                        real_url = m.group(1)
                        normalized = normalize_url(real_url)
                        if site_domain in normalized and normalized not in urls:
                            urls.append(normalized)
                    else:
                        normalized = normalize_url(href)
                        if site_domain in normalized and normalized.startswith("http") and normalized not in urls:
                            urls.append(normalized)
    except Exception:
        pass
    return urls


def save_article(article: dict, year: str, source_key: str) -> Path:
    year_dir = BASE_DIR / year
    year_dir.mkdir(parents=True, exist_ok=True)
    
    with article_counters_lock:
        key = (year, source_key)
        if key not in article_counters:
            existing = sorted(year_dir.glob(f"{source_key}_*.json"))
            if existing:
                m = re.search(r"_(\d+)$", existing[-1].stem)
                article_counters[key] = int(m.group(1)) + 1 if m else 1
            else:
                article_counters[key] = 1
        else:
            article_counters[key] += 1
        next_num = article_counters[key]

    filepath = year_dir / f"{source_key}_{next_num:03d}.json"
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(article, f, ensure_ascii=False, indent=2)
    return filepath


async def crawl_batch(client: httpx.AsyncClient, urls: list[str],
                       source_key: str, stats: dict):
    """Crawl 1 batch URLs song song."""
    tasks = [fetch_and_build(client, url) for url in urls]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    loop = asyncio.get_running_loop()
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
        fp = await loop.run_in_executor(cpu_executor, save_article, article, year, source_key)
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

    if use_year:
        for year in CRAWL_YEARS:
            for kw in SEARCH_KEYWORDS:
                logger.info(f"   \"{kw}\" năm {year}")
                found = await search_fn(client, kw, year=year)
                logger.info(f"     Found {len(found)} URL")
                for f in found:
                    all_urls.add(normalize_url(f))
                await asyncio.sleep(_random_delay())
    else:
        for kw in SEARCH_KEYWORDS:
            logger.info(f"   \"{kw}\"")
            found = await search_fn(client, kw)
            logger.info(f"     Found {len(found)} URL")
            for f in found:
                all_urls.add(normalize_url(f))
            await asyncio.sleep(_random_delay())

    if use_google_old and not IS_TEST_MODE:
        domain = {"vnexpress": "vnexpress.net", "tuoitre": "tuoitre.vn",
                  "vietnamnet": "vietnamnet.vn"}.get(source_key)
        if domain:
            for year in range(2010, 2020):
                for kw in ["FPT", "FPT Software"]:
                    logger.info(f"   Google: \"{kw}\" {year} site:{domain}")
                    found = await search_google_site(client, domain, kw, year)
                    before = len(all_urls)
                    for f in found:
                        all_urls.add(normalize_url(f))
                    logger.info(f"     Added +{len(all_urls) - before} URL mới")
                    await asyncio.sleep(4.0 + random.random() * 2)

    url_list = list(all_urls)[:MAX_ARTICLES_PER_SOURCE]
    logger.info(f"   Tổng: {len(all_urls)} unique -> crawl {len(url_list)}")

    stats = {"total": len(url_list), "success": 0, "failed": 0, "skipped": 0, "by_year": {}}

    batch_size = MAX_CONCURRENT
    for i in range(0, len(url_list), batch_size):
        batch = url_list[i:i + batch_size]
        logger.info(f"   Batch {i // batch_size + 1}/{(len(url_list) + batch_size - 1) // batch_size} - {len(batch)} URLs")
        await crawl_batch(client, batch, source_key, stats)
        await asyncio.sleep(_random_delay())

    return stats


async def crawl_thanhnien(client: httpx.AsyncClient) -> dict:
    """Crawl Thanh Niên: Playwright search trong ThreadPool + httpx async extract."""
    logger.info(f"\n{'='*60}")
    logger.info(f"   Thanh Niên")
    logger.info(f"{'='*60}")

    stats = {"total": 0, "success": 0, "failed": 0, "skipped": 0, "by_year": {}}

    loop = asyncio.get_running_loop()
    found_urls = await loop.run_in_executor(cpu_executor, run_all_thanhnien_search_in_thread, SEARCH_KEYWORDS)
    all_urls = set(normalize_url(f) for f in found_urls)

    if not IS_TEST_MODE:
        for year in range(2010, 2020):
            for kw in ["FPT", "FPT Software"]:
                logger.info(f"   Google: \"{kw}\" {year} site:thanhnien.vn")
                found = await search_google_site(client, "thanhnien.vn", kw, year)
                before = len(all_urls)
                for f in found:
                    all_urls.add(normalize_url(f))
                logger.info(f"     Added +{len(all_urls) - before} URL mới")
                await asyncio.sleep(4.0 + random.random() * 2)

    url_list = list(all_urls)[:MAX_ARTICLES_PER_SOURCE]
    stats["total"] = len(url_list)
    logger.info(f"   Tổng: {len(all_urls)} unique -> crawl {len(url_list)}")

    batch_size = MAX_CONCURRENT
    for i in range(0, len(url_list), batch_size):
        batch = url_list[i:i + batch_size]
        logger.info(f"   Batch {i // batch_size + 1}/{(len(url_list) + batch_size - 1) // batch_size} - {len(batch)} URLs")
        await crawl_batch(client, batch, "thanhnien", stats)
        await asyncio.sleep(_random_delay())

    return stats


async def crawl_tuoitre(client: httpx.AsyncClient) -> dict:
    """Crawl Tuổi Trẻ: Playwright search trong ThreadPool + httpx async extract."""
    logger.info(f"\n{'='*60}")
    logger.info(f"   Tuổi Trẻ")
    logger.info(f"{'='*60}")

    stats = {"total": 0, "success": 0, "failed": 0, "skipped": 0, "by_year": {}}

    loop = asyncio.get_running_loop()
    found_urls = await loop.run_in_executor(cpu_executor, run_tuoitre_search_in_thread, SEARCH_KEYWORDS)
    all_urls = set(normalize_url(f) for f in found_urls)

    if not IS_TEST_MODE:
        for year in range(2010, 2020):
            for kw in ["FPT", "FPT Software"]:
                logger.info(f"   Google: \"{kw}\" {year} site:tuoitre.vn")
                found = await search_google_site(client, "tuoitre.vn", kw, year)
                before = len(all_urls)
                for f in found:
                    all_urls.add(normalize_url(f))
                logger.info(f"     Added +{len(all_urls) - before} URL mới")
                await asyncio.sleep(4.0 + random.random() * 2)

    url_list = list(all_urls)[:MAX_ARTICLES_PER_SOURCE]
    stats["total"] = len(url_list)
    logger.info(f"   Tổng: {len(all_urls)} unique -> crawl {len(url_list)}")

    batch_size = MAX_CONCURRENT
    for i in range(0, len(url_list), batch_size):
        batch = url_list[i:i + batch_size]
        logger.info(f"   Batch {i // batch_size + 1}/{(len(url_list) + batch_size - 1) // batch_size} - {len(batch)} URLs")
        await crawl_batch(client, batch, "tuoitre", stats)
        await asyncio.sleep(_random_delay())

    return stats


async def crawl_vietnamnet(client: httpx.AsyncClient) -> dict:
    """Crawl VietnamNet: Playwright search + RSS + httpx async extract."""
    logger.info(f"\n{'='*60}")
    logger.info(f"   VietnamNet")
    logger.info(f"{'='*60}")

    stats = {"total": 0, "success": 0, "failed": 0, "skipped": 0, "by_year": {}}

    loop = asyncio.get_running_loop()
    
    rss_urls = await search_vietnamnet_rss(client)
    all_urls = set(normalize_url(f) for f in rss_urls)
    logger.info(f"   VietnamNet RSS: Found {len(all_urls)} URL")
    
    found_urls = await loop.run_in_executor(cpu_executor, run_vietnamnet_search_in_thread, SEARCH_KEYWORDS)
    for f in found_urls:
        all_urls.add(normalize_url(f))
    logger.info(f"   VietnamNet Playwright Search: Total unique now {len(all_urls)} URL")

    if not IS_TEST_MODE:
        for year in range(2010, 2020):
            for kw in ["FPT", "FPT Software"]:
                logger.info(f"   Google: \"{kw}\" {year} site:vietnamnet.vn")
                found = await search_google_site(client, "vietnamnet.vn", kw, year)
                before = len(all_urls)
                for f in found:
                    all_urls.add(normalize_url(f))
                logger.info(f"     Added +{len(all_urls) - before} URL mới")
                await asyncio.sleep(4.0 + random.random() * 2)

    url_list = list(all_urls)[:MAX_ARTICLES_PER_SOURCE]
    stats["total"] = len(url_list)
    logger.info(f"   Tổng: {len(all_urls)} unique -> crawl {len(url_list)}")

    batch_size = MAX_CONCURRENT
    for i in range(0, len(url_list), batch_size):
        batch = url_list[i:i + batch_size]
        logger.info(f"   Batch {i // batch_size + 1}/{(len(url_list) + batch_size - 1) // batch_size} - {len(batch)} URLs")
        await crawl_batch(client, batch, "vietnamnet", stats)
        await asyncio.sleep(_random_delay())

    return stats


def clean_old_data():
    for item in BASE_DIR.iterdir():
        if item.is_dir() and re.match(r"^20\d{2}$", item.name):
            shutil.rmtree(item)
            logger.info(f"  Xóa: {item.name}/")
    s = BASE_DIR / "crawl_summary.json"
    if s.exists():
        s.unlink()


async def main():
    start_time = time.time()
    import argparse
    parser = argparse.ArgumentParser(description="FPT News Crawler")
    parser.add_argument("--test", action="store_true", help="Chạy chế độ thử nghiệm nhanh (2025-2026, ít keywords)")
    args, unknown = parser.parse_known_args()

    global CRAWL_YEARS, SEARCH_KEYWORDS, IS_TEST_MODE
    if args.test:
        logger.info("  [TEST MODE] Chỉ quét năm 2025-2026 với 3 keywords chính")
        CRAWL_YEARS = [2025, 2026]
        SEARCH_KEYWORDS = ["FPT", "Tập đoàn FPT", "FPT Software"]
        IS_TEST_MODE = True

    logger.info("=" * 60)
    logger.info("  FPT NEWS CRAWLER v7 (Optimized)")
    logger.info(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info(f"  Năm: {CRAWL_YEARS[0]}–{CRAWL_YEARS[-1]}")
    logger.info(f"  Async: {MAX_CONCURRENT} concurrent requests per domain")
    logger.info("=" * 60)

    logger.info("\n  Dọn dẹp dữ liệu cũ...")
    clean_old_data()

    total_stats = {"sources": {}, "total_articles": 0}

    limits = httpx.Limits(
        max_connections=100,
        max_keepalive_connections=50,
        keepalive_expiry=30.0
    )

    stop_logging = threading.Event()
    def periodic_metrics_log():
        while not stop_logging.is_set():
            time.sleep(10.0)
            metrics.log_progress()

    metrics_thread = threading.Thread(target=periodic_metrics_log, daemon=True)
    metrics_thread.start()

    async with httpx.AsyncClient(http2=True, verify=True, limits=limits) as client:
        async def worker_vnexpress():
            try:
                s = await crawl_with_httpx(client, "vnexpress", "VnExpress",
                                            search_vnexpress, use_year=True, use_google_old=True)
                return "vnexpress", s
            except Exception as e:
                logger.error(f"   VnExpress: {e}")
                return "vnexpress", {"error": str(e)}

        async def worker_tuoitre():
            try:
                s = await crawl_tuoitre(client)
                return "tuoitre", s
            except Exception as e:
                logger.error(f"   Tuổi Trẻ: {e}")
                return "tuoitre", {"error": str(e)}

        async def worker_thanhnien():
            try:
                s = await crawl_thanhnien(client)
                return "thanhnien", s
            except Exception as e:
                logger.error(f"   Thanh Niên: {e}")
                return "thanhnien", {"error": str(e)}

        async def worker_vietnamnet():
            try:
                s = await crawl_vietnamnet(client)
                return "vietnamnet", s
            except Exception as e:
                logger.error(f"   VietnamNet: {e}")
                return "vietnamnet", {"error": str(e)}

        results = await asyncio.gather(
            worker_vnexpress(),
            worker_tuoitre(),
            worker_thanhnien(),
            worker_vietnamnet()
        )

        for source_key, s in results:
            total_stats["sources"][source_key] = s
            if "error" not in s:
                total_stats["total_articles"] += s["success"]

    stop_logging.set()
    metrics.log_progress()

    logger.info("\n" + "=" * 60)
    logger.info("   KẾT QUẢ CRAWL")
    logger.info("=" * 60)
    logger.info(f"  Tổng số bài đã lưu: {total_stats['total_articles']} bài")

    all_years = {}
    for sk, st in total_stats["sources"].items():
        if "error" in st:
            logger.info(f"  {sk}: {st['error']}")
        else:
            logger.info(f"  {sk}: Success: {st['success']} Failed: {st['failed']}")
            for y, c in sorted(st.get("by_year", {}).items()):
                logger.info(f"    +-- {y}: {c}")
                all_years[y] = all_years.get(y, 0) + c

    logger.info("\n  Phân bổ năm:")
    for y in sorted(all_years):
        logger.info(f"    {y}: {all_years[y]} bài")

    BASE_DIR.mkdir(parents=True, exist_ok=True)
    with open(BASE_DIR / "crawl_summary.json", "w", encoding="utf-8") as f:
        json.dump(total_stats, f, ensure_ascii=False, indent=2)

    elapsed_time = time.time() - start_time
    logger.info(f"\n  [Benchmark] Tổng thời gian thực thi: {elapsed_time:.2f} giây")
    logger.info("   DONE!")


if __name__ == "__main__":
    asyncio.run(main())
