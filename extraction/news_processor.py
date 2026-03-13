"""
extraction/news_processor.py

Loads crawled news articles from crawl_data_news/ into the Knowledge Graph
as NewsEvent nodes with appropriate relations.

Input format: JSON files produced by crawler_news.py
    Each file contains a list of article dicts with keys:
        title / headline, url, published_at / date, source,
        content / summary, sentiment (optional)

The processor:
1. Walks crawl_data_news/YYYY/ directories
2. Normalizes each article into a NewsEvent node
3. Assigns ESG pillar via keyword classification
4. Infers sentiment via keywords (if not pre-labelled)
5. Ingests into KG via GraphBuilder.add_news_event()
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Keyword lists for pillar classification and sentiment inference
# ---------------------------------------------------------------------------

_PILLAR_KEYWORDS: dict[str, list[str]] = {
    "E": [
        "môi trường", "environment", "carbon", "khí thải", "emission",
        "năng lượng", "energy", "tái tạo", "renewable", "nước", "water",
        "rác thải", "waste", "ô nhiễm", "pollution", "biến đổi khí hậu",
        "climate", "xanh", "green", "phát thải", "solar", "mặt trời",
        "xả thải", "discharge", "biodiversity", "đa dạng sinh học",
    ],
    "S": [
        "lao động", "labor", "nhân viên", "employee", "worker",
        "cộng đồng", "community", "xã hội", "social", "tai nạn",
        "accident", "an toàn", "safety", "đào tạo", "training",
        "lương", "salary", "wage", "phân biệt đối xử", "discrimination",
        "quyền lao động", "labor rights", "y tế", "health",
    ],
    "G": [
        "quản trị", "governance", "hội đồng", "board", "cổ đông",
        "shareholder", "minh bạch", "transparency", "tham nhũng",
        "corruption", "gian lận", "fraud", "kiểm toán", "audit",
        "công bố", "disclosure", "pháp lý", "legal", "vi phạm", "violation",
        "phạt", "fine", "penalty", "bị xử phạt", "sanctioned",
    ],
}

_NEGATIVE_KEYWORDS: list[str] = [
    "phạt", "vi phạm", "bị phạt", "xử phạt", "ô nhiễm", "tai nạn",
    "gian lận", "tham nhũng", "kiện", "lawsuit", "scandal", "bê bối",
    "fine", "penalty", "violation", "fraud", "accident", "pollution",
    "contamination", "illegal", "bất hợp pháp", "lạm dụng", "abuse",
    "cáo buộc", "allegation", "điều tra", "investigation", "arrested",
    "bắt giữ", "collapse", "sụp đổ", "bankrupt", "phá sản",
]

_POSITIVE_KEYWORDS: list[str] = [
    "đạt", "thành công", "hoàn thành", "giải thưởng", "award",
    "chứng nhận", "certificate", "recognition", "ghi nhận",
    "tăng trưởng", "growth", "đầu tư", "investment", "hợp tác",
    "partnership", "cam kết", "commitment", "đổi mới", "innovation",
    "bền vững", "sustainable", "xanh", "green achievement",
]


class NewsProcessor:
    """
    Processes crawled news articles from crawl_data_news/ into KG NewsEvent nodes.

    Parameters
    ----------
    news_dir : str | Path
        Root directory of the news data (default: crawl_data_news/).
    company_id : str
        KG company node ID to link events to (e.g. "COMP_FPT").
    """

    def __init__(self, news_dir: str | Path, company_id: str) -> None:
        self.news_dir = Path(news_dir)
        self.company_id = company_id

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load_all_articles(self, years: list[int] | None = None) -> list[dict]:
        """
        Walk news_dir/YYYY/ subdirectories and load all article JSON files.

        Parameters
        ----------
        years : list[int] | None
            If provided, only load articles from those years.

        Returns
        -------
        list[dict]
            Normalized article dicts ready for KG ingestion.
        """
        articles: list[dict] = []

        if not self.news_dir.exists():
            logger.warning("News directory not found: %s", self.news_dir)
            return articles

        for year_dir in sorted(self.news_dir.iterdir()):
            if not year_dir.is_dir():
                continue
            try:
                year = int(year_dir.name)
            except ValueError:
                continue

            if years and year not in years:
                continue

            for json_file in sorted(year_dir.glob("*.json")):
                try:
                    loaded = self._load_json_file(json_file)
                    normalized = [self._normalize_article(a, year) for a in loaded]
                    articles.extend([a for a in normalized if a is not None])
                except Exception as e:
                    logger.warning("Failed to load %s: %s", json_file, e)

        logger.info(
            "Loaded %d articles from %s", len(articles), self.news_dir
        )
        return articles

    def ingest_into_kg(self, graph_builder, years: list[int] | None = None) -> int:
        """
        Load all articles and ingest them into the KG via graph_builder.

        Parameters
        ----------
        graph_builder : GraphBuilder
            The KG builder instance.
        years : list[int] | None
            Optional year filter.

        Returns
        -------
        int
            Number of NewsEvent nodes created.
        """
        articles = self.load_all_articles(years=years)
        count = 0
        for article in articles:
            try:
                graph_builder.add_news_event(article, self.company_id)
                count += 1
            except Exception as e:
                logger.debug("Failed to ingest article '%s': %s", article.get("headline", "?"), e)

        logger.info("Ingested %d NewsEvent nodes for %s", count, self.company_id)
        return count

    # ------------------------------------------------------------------
    # Normalization helpers
    # ------------------------------------------------------------------

    def _load_json_file(self, path: Path) -> list[dict]:
        """Load a JSON file that may contain a list or a single article dict."""
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            # Some files wrap a list under an "articles" or "data" key
            for key in ("articles", "data", "results", "items"):
                if key in data and isinstance(data[key], list):
                    return data[key]
            return [data]
        return []

    def _normalize_article(self, raw: dict, year: int) -> dict | None:
        """Convert a raw article dict into the standard NewsEvent format."""
        if not isinstance(raw, dict):
            return None

        # Headline — try multiple possible key names
        headline = (
            raw.get("title")
            or raw.get("headline")
            or raw.get("name")
            or raw.get("subject")
            or ""
        ).strip()

        if not headline:
            return None

        # Content
        content = (
            raw.get("content")
            or raw.get("summary")
            or raw.get("description")
            or raw.get("body")
            or ""
        ).strip()

        # URL
        url = raw.get("url") or raw.get("link") or raw.get("href") or ""

        # Source
        source = (
            raw.get("source")
            or raw.get("publisher")
            or raw.get("domain")
            or self._extract_domain(url)
            or "Unknown"
        )

        # Published date
        published_at = self._parse_date(
            raw.get("published_at")
            or raw.get("date")
            or raw.get("pub_date")
            or raw.get("publishedAt")
            or str(year)
        )

        # Pillar classification
        full_text = f"{headline} {content}".lower()
        pillar = raw.get("pillar") or self._classify_pillar(full_text)

        # Sentiment
        sentiment_raw = raw.get("sentiment") or raw.get("label") or ""
        sentiment = self._normalize_sentiment(sentiment_raw, full_text)

        return {
            "headline": headline,
            "content": content,
            "url": url,
            "source": source,
            "published_at": published_at,
            "pillar": pillar,
            "sentiment": sentiment,
            "year": year,
        }

    # ------------------------------------------------------------------
    # Classification helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _classify_pillar(text: str) -> str:
        """Classify article into E / S / G / Mixed by keyword matching."""
        scores: dict[str, int] = {"E": 0, "S": 0, "G": 0}
        for pillar, keywords in _PILLAR_KEYWORDS.items():
            for kw in keywords:
                if kw.lower() in text:
                    scores[pillar] += 1

        max_score = max(scores.values())
        if max_score == 0:
            return "Mixed"

        winners = [p for p, s in scores.items() if s == max_score]
        if len(winners) == 1:
            return winners[0]
        return "Mixed"

    @staticmethod
    def _normalize_sentiment(raw: str, text: str) -> str:
        """Normalize or infer sentiment label."""
        raw_lower = raw.lower()
        if raw_lower in ("negative", "neg", "-1", "bad", "tiêu cực"):
            return "Negative"
        if raw_lower in ("positive", "pos", "+1", "good", "tích cực"):
            return "Positive"
        if raw_lower in ("neutral", "neu", "0", "trung lập"):
            return "Neutral"

        # Infer from text keywords
        neg_hits = sum(1 for kw in _NEGATIVE_KEYWORDS if kw in text)
        pos_hits = sum(1 for kw in _POSITIVE_KEYWORDS if kw in text)

        if neg_hits > pos_hits:
            return "Negative"
        if pos_hits > neg_hits:
            return "Positive"
        return "Neutral"

    @staticmethod
    def _parse_date(raw: str | None) -> str:
        """Parse a date string to ISO format YYYY-MM-DD, best effort."""
        if not raw:
            return ""
        raw = str(raw).strip()

        # Already ISO
        if re.match(r"^\d{4}-\d{2}-\d{2}", raw):
            return raw[:10]

        # Try common formats
        for fmt in ("%d/%m/%Y", "%Y/%m/%d", "%d-%m-%Y", "%B %d, %Y", "%Y"):
            try:
                return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
            except ValueError:
                continue

        # Fallback: extract 4-digit year
        m = re.search(r"(\d{4})", raw)
        if m:
            return f"{m.group(1)}-01-01"
        return ""

    @staticmethod
    def _extract_domain(url: str) -> str:
        """Extract domain name from URL as source label."""
        m = re.search(r"https?://(?:www\.)?([^/]+)", url)
        if m:
            domain = m.group(1)
            # Return human-readable name for known Vietnamese news sites
            _KNOWN: dict[str, str] = {
                "vnexpress.net": "VnExpress",
                "laodong.vn": "Lao Động",
                "cafef.vn": "CafeF",
                "baomoi.com": "Báo Mới",
                "tuoitre.vn": "Tuổi Trẻ",
                "thanhnien.vn": "Thanh Niên",
                "dantri.com.vn": "Dân Trí",
                "vietnambiz.vn": "VietnamBiz",
                "vietstock.vn": "Vietstock",
                "tinnhanhchungkhoan.vn": "Tinnhanh CK",
            }
            return _KNOWN.get(domain, domain)
        return ""
