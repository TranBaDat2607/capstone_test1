# -*- coding: utf-8 -*-
"""Static configuration: keyword groups, source domains, defaults.

Keywords here are for RETRIEVAL ONLY (to surface rare relevant articles), not
for filtering. The downstream model decides what is actually evidence.
"""

from __future__ import annotations

KEYWORD_GROUPS = [
    ["ESG", "phát triển bền vững", "báo cáo phát triển bền vững", "công trình xanh"],
    ["môi trường", "xả thải", "ô nhiễm", "xử phạt môi trường"],
    ["phát thải", "năng lượng tái tạo", "Net Zero", "giảm phát thải"],
    ["tai nạn lao động", "nợ bảo hiểm", "thao túng", "kiểm toán ngoại trừ"],
]

SITE_DOMAINS = [
    "cafef.vn",
    "vietstock.vn",
    "tinnhanhchungkhoan.vn",
    "vneconomy.vn",
    "baodautu.vn",
    "theleader.vn",
    "nhadautu.vn",
    "ndh.vn",
    "vnexpress.net",
    "tuoitre.vn",
    "thanhnien.vn",
    "dantri.com.vn",
    "plo.vn",
    "laodong.vn",
    "baotainguyenmoitruong.vn",
    "moitruong.net.vn",
]

SKIP_URL_SUBSTRINGS = [
    "google.com", "youtube.com", "youtu.be", "facebook.com", "fb.com",
    "tiktok.com", "twitter.com", "x.com", "instagram.com", "linkedin.com",
    "/video/", "/videos/", "/photo/", "/gallery/", "/tag/", "/chuyen-muc/",
    ".pdf", ".zip", ".doc", ".xls",
]

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

DEFAULT_SINCE_YEARS = 5
DEFAULT_MAX_ARTICLES = 40
DEFAULT_DOMAIN_DELAY = 2.0
DEFAULT_TIMEOUT = 20
DEFAULT_RETRIES = 3
DEFAULT_OUTPUT_DIR = "data/outputs/news"
DEFAULT_CACHE_DIR = "data/outputs/news/_cache"
