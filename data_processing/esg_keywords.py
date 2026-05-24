"""Curated Vietnamese (+ English fallback) ESG keyword dictionary.

Used as a fast pre-filter: any sentence containing at least one of these
phrases is forwarded to the semantic GRI mapper for finer classification.

Phrases are matched case-insensitively as whole-word/substring matches after
NFC normalization. Keep entries to multi-word phrases where possible — single
words like "nước" or "khí" produce too many false positives in financial text.
"""

from __future__ import annotations

import re
import unicodedata


ESG_KEYWORDS: dict[str, list[str]] = {
    "E": [
        # Climate / emissions
        "phát thải", "khí nhà kính", "khí thải", "carbon", "co2", "co₂",
        "biến đổi khí hậu", "trung hòa carbon", "net zero", "net-zero",
        "scope 1", "scope 2", "scope 3", "phạm vi 1", "phạm vi 2", "phạm vi 3",
        # Energy
        "năng lượng tái tạo", "năng lượng mặt trời", "điện mặt trời", "điện gió",
        "tiết kiệm năng lượng", "hiệu suất năng lượng", "tiêu thụ năng lượng",
        # Water
        "tiết kiệm nước", "nước thải", "xử lý nước", "tài nguyên nước",
        "tiêu thụ nước", "khai thác nước",
        # Waste / circular
        "chất thải", "tái chế", "tái sử dụng", "kinh tế tuần hoàn",
        "phân loại rác", "rác thải nhựa", "chất thải nguy hại",
        # Materials / biodiversity
        "nguyên vật liệu tái chế", "đa dạng sinh học", "bảo tồn", "rừng",
        # General environment
        "môi trường", "bảo vệ môi trường", "thân thiện môi trường",
        "phát triển bền vững", "bền vững", "sinh thái",
        "iso 14001", "iso 50001",
    ],
    "S": [
        # Workforce
        "người lao động", "nhân viên", "đào tạo", "bồi dưỡng", "tuyển dụng",
        "phúc lợi", "lương thưởng", "thu nhập bình quân",
        # Safety
        "an toàn lao động", "vệ sinh lao động", "an toàn vệ sinh lao động",
        "tai nạn lao động", "bệnh nghề nghiệp", "phòng cháy chữa cháy",
        "ohsas", "iso 45001",
        # Diversity / equality
        "bình đẳng giới", "đa dạng", "phụ nữ", "nữ giới", "lao động nữ",
        "phân biệt đối xử", "quyền con người", "công đoàn",
        "lao động trẻ em", "lao động cưỡng bức",
        # Community
        "cộng đồng", "trách nhiệm xã hội", "an sinh xã hội", "từ thiện",
        "tài trợ", "ủng hộ", "thiện nguyện", "đóng góp xã hội",
        # Customer / product
        "an toàn sản phẩm", "chất lượng sản phẩm", "khách hàng",
        "bảo mật thông tin", "quyền riêng tư",
        # Suppliers
        "chuỗi cung ứng", "nhà cung cấp",
    ],
    "G": [
        "quản trị", "quản trị công ty", "quản trị doanh nghiệp",
        "hội đồng quản trị", "ban kiểm soát", "ban điều hành",
        "cổ đông", "đại hội đồng cổ đông", "minh bạch", "công bố thông tin",
        "kiểm toán", "kiểm soát nội bộ", "quản trị rủi ro", "quản lý rủi ro",
        "đạo đức kinh doanh", "bộ quy tắc ứng xử", "chống tham nhũng",
        "hối lộ", "xung đột lợi ích", "tuân thủ", "tuân thủ pháp luật",
        "thù lao", "lương thưởng hđqt",
        # English fallbacks (Vietnamese reports sometimes use these directly)
        "esg", "csr", "sustainability", "gri", "tcfd", "sdg",
    ],
}


def _normalize(s: str) -> str:
    return unicodedata.normalize("NFC", s).lower()


def _compile() -> list[tuple[str, str, re.Pattern[str]]]:
    """Return list of (pillar, keyword, compiled_pattern)."""
    out: list[tuple[str, str, re.Pattern[str]]] = []
    for pillar, kws in ESG_KEYWORDS.items():
        for kw in kws:
            kw_n = _normalize(kw)
            # Word-ish boundary: not preceded/followed by a Vietnamese letter
            pattern = re.compile(
                rf"(?<![\wÀ-ỹ]){re.escape(kw_n)}(?![\wÀ-ỹ])",
                re.IGNORECASE,
            )
            out.append((pillar, kw, pattern))
    return out


_COMPILED = _compile()


def find_matches(sentence: str) -> list[tuple[str, str]]:
    """Return list of (pillar, keyword) hits in `sentence`. Empty if none."""
    sent_n = _normalize(sentence)
    hits: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for pillar, kw, pat in _COMPILED:
        if pat.search(sent_n):
            key = (pillar, kw)
            if key not in seen:
                hits.append(key)
                seen.add(key)
    return hits


def is_esg_candidate(sentence: str) -> bool:
    return bool(find_matches(sentence))
