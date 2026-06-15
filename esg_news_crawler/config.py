# -*- coding: utf-8 -*-
"""Static configuration: keyword groups, source domains, defaults.

Keywords here are for RETRIEVAL ONLY (to surface rare relevant articles), not
for filtering. The downstream model decides what is actually evidence.
"""

from __future__ import annotations

# ------------------------------------------------------------------
# Keyword OR-groups. Each group becomes ONE query per identity phrase
# (joined with OR) to keep the request count manageable while still
# casting a wide net across E / S / G claims and controversies.
# ------------------------------------------------------------------
KEYWORD_GROUPS = [
    # Sustainability claims (what the report would boast about)
    ["ESG", "phát triển bền vững", "báo cáo phát triển bền vững", "công trình xanh"],
    # Environmental conduct / controversy
    ["môi trường", "xả thải", "ô nhiễm", "xử phạt môi trường"],
    # Emissions / energy transition
    ["phát thải", "năng lượng tái tạo", "Net Zero", "giảm phát thải"],
    # Social + governance signals
    ["tai nạn lao động", "nợ bảo hiểm", "thao túng", "kiểm toán ngoại trừ"],
]

# ------------------------------------------------------------------
# Curated domains worth a site:-restricted query. These cover the
# financial media that actually mention mid-cap tickers, environment
# outlets, and regulators.
# ------------------------------------------------------------------
SITE_DOMAINS = [
    # financial / market media (richest for these tickers)
    "cafef.vn",
    "vietstock.vn",
    "tinnhanhchungkhoan.vn",
    "vneconomy.vn",
    "baodautu.vn",
    "theleader.vn",
    "nhadautu.vn",
    "ndh.vn",
    # general national press
    "vnexpress.net",
    "tuoitre.vn",
    "thanhnien.vn",
    "dantri.com.vn",
    "plo.vn",
    "laodong.vn",
    # environment-focused
    "baotainguyenmoitruong.vn",
    "moitruong.net.vn",
]

# Domains/paths to drop outright (not news articles).
SKIP_URL_SUBSTRINGS = [
    "google.com", "youtube.com", "youtu.be", "facebook.com", "fb.com",
    "tiktok.com", "twitter.com", "x.com", "instagram.com", "linkedin.com",
    "/video/", "/videos/", "/photo/", "/gallery/", "/tag/", "/chuyen-muc/",
    ".pdf", ".zip", ".doc", ".xls",
]

# Realistic desktop User-Agents to rotate through.
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) "
    "Gecko/20100101 Firefox/126.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
]

# Defaults (overridable via run.py CLI).
DEFAULT_SINCE_YEARS = 5        # events are rare → wide window
DEFAULT_MAX_ARTICLES = 40      # per company, after dedup
DEFAULT_DOMAIN_DELAY = 2.0     # min seconds between hits to the SAME domain
DEFAULT_TIMEOUT = 20
DEFAULT_RETRIES = 3
DEFAULT_OUTPUT_DIR = "data/outputs/news"
DEFAULT_CACHE_DIR = "data/outputs/news/_cache"
