"""Deterministic rejection rules for the YAKE candidate pool.

This module is the executable form of the rejection protocol in
`KEYWORD_DICT_PLAN.md` §Step 2. Every constant carries the rule number it
implements; `prune_candidates.py` applies them in the order they appear in
`RULE_ORDER` and records the first rule that fires for each rejected term.

Rules (verbatim from KEYWORD_DICT_PLAN.md):
  1. Tên riêng (người, tổ chức, địa danh)
  2. Số hiệu văn bản, ngày tháng
  3. Thuật ngữ pháp lý chung
  4. Cấu trúc văn bản
  5. Đơn vị đo lường thuần
  6. Cụm từ mơ hồ không có nội hàm ESG

A seventh pseudo-rule ("0 — shape") covers length / punctuation /
all-numeric junk that is independent of language.
"""

from __future__ import annotations

import re
import unicodedata


def normalize(s: str) -> str:
    """NFC + lowercase + collapse internal whitespace."""
    s = unicodedata.normalize("NFC", s).lower().strip()
    return re.sub(r"\s+", " ", s)


# ---------------------------------------------------------------------------
# Rule 0 — shape filters (length, punctuation, pure-numeric).
# ---------------------------------------------------------------------------

MIN_LENGTH = 2
MAX_LENGTH = 60
MAX_PUNCT_RATIO = 0.5

_PUNCT_RE = re.compile(r"[^\w\sÀ-ỹ]", re.UNICODE)
_DIGIT_ONLY_RE = re.compile(r"^[\d\s\.,/_-]+$")


# Single tokens that carry no content on their own. A keyword whose
# tokens are ALL drawn from this set is rejected as Rule 3 filler. This
# catches YAKE fragments like "thông tin theo" or "của doanh" that the
# exact-match stoplists miss because YAKE produces every n-gram window.
TOKEN_STOPWORDS: set[str] = {
    # Function words
    "các", "của", "và", "là", "được", "có", "cho", "từ", "đến", "với",
    "theo", "tại", "trong", "ngoài", "trên", "dưới", "sau", "trước",
    "này", "đó", "kia", "ấy", "nào", "gì", "ai", "đâu",
    "một", "hai", "ba", "bốn", "năm", "sáu", "bảy", "tám", "chín", "mười",
    "thì", "mà", "nếu", "khi", "vì", "do", "nên", "hoặc", "hay",
    "không", "chưa", "đã", "đang", "sẽ", "vẫn", "cũng",
    "phải", "cần", "muốn", "nên",
    "ra", "vào", "lên", "xuống", "qua", "lại",
    # High-frequency document/topic nouns that are not ESG content
    "thông", "tin", "báo", "cáo", "ban", "ngày", "tháng", "năm",
    "công", "ty", "doanh", "nghiệp", "việc", "vấn", "đề",
    "chứng", "khoán", "thị", "trường", "tài", "chính",
    "định", "lập", "dẫn", "hướng", "đại", "chúng",
    "the", "of", "a", "an", "to", "in", "on", "for", "by",
}


# ---------------------------------------------------------------------------
# Rule 2 — document IDs, dates, regulation numbers.
# ---------------------------------------------------------------------------

REGEX_RULES: list[tuple[str, re.Pattern[str], str]] = [
    ("2", re.compile(r"\b\d+[-/]\d+[-/]?tt[-/]?[a-zà-ỹ]+\b", re.IGNORECASE),
     "regulation id (e.g. 96-2020-TT-BTC)"),
    ("2", re.compile(r"\bngày\s+\d+\s+tháng\s+\d+", re.IGNORECASE),
     "Vietnamese date phrase"),
    ("2", re.compile(r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b"),
     "numeric date"),
    ("2", re.compile(r"\b(19|20)\d{2}\b"),
     "bare year"),
    ("2", re.compile(r"\b(điều|khoản|mục)\s+\d+\b", re.IGNORECASE),
     "article/clause number"),
]


# ---------------------------------------------------------------------------
# Rule 1 — proper names (only the obvious ones; rest goes to manual review).
# ---------------------------------------------------------------------------

KNOWN_ENTITIES: set[str] = {normalize(s) for s in [
    "việt nam", "vn", "hà nội", "hồ chí minh", "tp hcm", "tp.hcm",
    "ifc", "ifc hà nội", "ssc", "vbcsd", "vcci",
    "bộ tài chính", "ủy ban chứng khoán", "ủy ban chứng khoán nhà nước",
    "chính phủ", "thủ tướng", "thủ tướng chính phủ",
    "gri", "csi",
    "navigation book", "page",
]}


# ---------------------------------------------------------------------------
# Rule 3 — generic legal filler.
# ---------------------------------------------------------------------------

STOPLIST_LEGAL_FILLER: set[str] = {normalize(s) for s in [
    # Generic legal connectives
    "căn cứ", "ban hành", "quy định", "quy định tại", "quy định của",
    "trường hợp", "theo đó", "theo quy định", "có liên quan", "liên quan",
    "được thực hiện", "thực hiện", "thực hiện các", "thực hiện theo",
    "thực hiện việc", "việc thực hiện", "thực hiện công",
    "đối với", "trong trường hợp", "trường hợp này",
    "phải có", "có thể", "có nội", "có nội dung",
    "bao gồm", "kèm theo", "đính kèm",
    "như sau", "sau đây", "trên đây", "dưới đây",
    "nội dung", "nội dung của",
    "theo quy", "theo các", "theo từng",
    "đảm bảo", "bảo đảm",
    "xác định", "được xác định",
    "có trách nhiệm", "trách nhiệm",
    "yêu cầu", "các yêu cầu",
    "phù hợp", "phù hợp với",
    "tổ chức", "tổ chức thực hiện", "tổ chức và",
    "trình bày", "được trình bày",
    "áp dụng", "được áp dụng",
    # Document/topic words that aren't ESG content on their own
    "thông tin", "các thông tin", "thông tin của", "thông tin theo",
    "thông tin định", "thông tin điện", "thông tin thông", "trang thông tin",
    "thông báo", "thông báo công", "thông báo của",
    "báo cáo", "báo cáo tài", "cáo tài chính", "báo cáo tài chính",
    "lập báo cáo", "dẫn lập báo", "hướng dẫn lập báo",
    "công bố", "công bố thông", "công bố thông tin",
    "công ty", "của công ty", "công ty cổ phần",
    "doanh nghiệp", "của doanh nghiệp", "các doanh nghiệp",
    "doanh nghiệp xây", "doanh nghiệp cung", "doanh của doanh",
    "định tại điều", "tại điều", "tại khoản",
    # Securities-domain words (corpus topic, not ESG)
    "chứng khoán", "chứng khoán nhà", "chứng khoán nhà nước",
    "ban chứng khoán", "ủy ban chứng khoán", "ban chứng",
    "chứng khoán đại", "chứng khoán việt", "chứng khoán phải",
    "trường chứng khoán", "thị trường chứng khoán",
    "khoán việt nam", "khoán nhà nước", "khoán đại chúng",
    "khoán phải công", "giao dịch chứng", "giao dịch chứng khoán",
    "dịch chứng", "dịch chứng khoán", "chứng chỉ quỹ",
    "đại chúng", "công ty đại chúng",
    # Common fragments
    "the board", "the group", "the company", "board of directors",
    # Transaction / securities procedure fragments
    "giao dịch", "ngày giao dịch", "hiện giao dịch", "thông tin giao",
    "giao dịch của", "giao dịch chứng",
    "luật chứng khoán", "luật",
    "giấy chứng nhận", "giấy chứng", "giấy phép",
    "bản báo cáo", "trình báo cáo", "báo cáo tổng",
    "trường hợp công", "bản quy phạm", "kèm theo thông",
    "tổng công", "tổng công ty", "công ty quản", "công ty cung",
    "tên công", "tên của", "đối tượng công",
    "nhà đầu", "nhà đầu tư", "của nhà đầu",
    "đại hội", "đại hội đồng", "của đại hội", "đại hội nhà",
    "đại chúng quy", "quỹ đại chúng",
    "việt nam điều", "nghĩa việt nam", "tại việt nam",
    "cộng hòa xã hội", "xã hội chủ", "chủ nghĩa",
    "nhà nước", "của nhà",
    "kinh doanh", "đầu tư",
    "quyết của công", "quyết định",
    "phiếu của công", "cổ phiếu",
    "chứng chỉ",
    # Stand-alone single-token fragments (1-syllable shards of ESG terms;
    # if the full phrase is present, it will appear separately).
    "động", "lao", "giao", "dịch", "thực", "bền", "vững", "nhà",
    "phát", "triển", "báo", "cáo", "công", "ty",
]}


# ---------------------------------------------------------------------------
# Rule 4 — document structure markers.
# ---------------------------------------------------------------------------

STOPLIST_DOC_STRUCTURE: set[str] = {normalize(s) for s in [
    "chương", "điều", "khoản", "mục", "phụ lục", "điểm", "đoạn",
    "phần", "chương i", "chương ii", "chương iii", "chương iv",
    "tiết", "tiểu mục",
    "hướng dẫn", "hướng dẫn lập", "hướng dẫn các",
    "công báo", "official gazette",
    "navigation book", "navigation book page", "book page",
    "page", "trang", "số trang",
    "table", "table of contents", "mục lục",
    "cộng hòa", "cộng hòa xã hội", "cộng hoà",
    "độc lập", "tự do", "hạnh phúc",
    "nội bộ ban", "ban hành kèm",
]}


# ---------------------------------------------------------------------------
# Rule 5 — pure measurement units (standalone, not coupled with ESG content).
# ---------------------------------------------------------------------------

STOPLIST_UNITS: set[str] = {normalize(s) for s in [
    "đồng", "triệu đồng", "tỷ đồng", "nghìn đồng", "ngàn đồng",
    "kg", "g", "tấn", "kilogram", "kilôgam",
    "m3", "m2", "m³", "m²", "mét", "km",
    "%", "phần trăm",
    "usd", "vnđ", "vnd",
]}


# ---------------------------------------------------------------------------
# Rule 6 — vague phrases (only clearly empty ones; borderline → review).
# ---------------------------------------------------------------------------

STOPLIST_VAGUE: set[str] = {normalize(s) for s in [
    "được thực hiện", "có liên quan", "các vấn đề", "vấn đề",
    "các yếu tố", "yếu tố", "các bên", "bên liên quan",
    "các hoạt động", "hoạt động", "các loại", "loại",
    "các nội dung", "các điều kiện", "điều kiện",
    "trong quá trình", "quá trình",
    "nói chung", "nói riêng", "cụ thể",
    "tổng thể", "chi tiết",
    "đầy đủ", "kịp thời", "chính xác",
]}


# ---------------------------------------------------------------------------
# Apply rules in this order. First match wins; "0-shape" runs first so we
# never feed garbage strings into the substring stoplists.
# ---------------------------------------------------------------------------

RULE_ORDER = ("0-shape", "1", "2", "3", "4", "5", "6")

RULE_LABEL: dict[str, str] = {
    "0-shape": "shape filter (length, punctuation, numeric-only)",
    "1": "proper name (Rule 1)",
    "2": "document id / date (Rule 2)",
    "3": "generic legal filler (Rule 3)",
    "4": "document structure marker (Rule 4)",
    "5": "pure measurement unit (Rule 5)",
    "6": "vague phrase (Rule 6)",
}


def classify(keyword: str) -> tuple[str | None, str]:
    """Return (rule_id, reason) if the keyword should be rejected, else (None, "").

    `rule_id` is one of `RULE_ORDER`. `reason` is a short human-readable
    string suitable for the CSV `reason` column. The classifier never
    accepts a term — non-rejection means "send to manual review".
    """
    raw = keyword.strip()
    if not raw:
        return "0-shape", "empty after strip"

    # Shape filter on the raw form first (length is measured on raw, not
    # normalized — Vietnamese accents shouldn't inflate length).
    if len(raw) < MIN_LENGTH:
        return "0-shape", f"length < {MIN_LENGTH}"
    if len(raw) > MAX_LENGTH:
        return "0-shape", f"length > {MAX_LENGTH}"
    if _DIGIT_ONLY_RE.match(raw):
        return "0-shape", "numeric-only"
    punct_chars = len(_PUNCT_RE.findall(raw))
    non_space = len(re.sub(r"\s+", "", raw))
    if non_space > 0 and punct_chars / non_space > MAX_PUNCT_RATIO:
        return "0-shape", "mostly punctuation"

    norm = normalize(raw)

    # Regex rules (rules 1/2 patterns).
    for rule_id, pat, reason in REGEX_RULES:
        if pat.search(norm):
            return rule_id, reason

    # Exact-match stoplists.
    if norm in KNOWN_ENTITIES:
        return "1", "known proper noun"
    if norm in STOPLIST_DOC_STRUCTURE:
        return "4", "document structure stoplist"
    if norm in STOPLIST_UNITS:
        return "5", "measurement unit stoplist"
    if norm in STOPLIST_LEGAL_FILLER:
        return "3", "legal filler stoplist"
    if norm in STOPLIST_VAGUE:
        return "6", "vague phrase stoplist"

    # All-stopword tokens → YAKE fragment with no content.
    tokens = norm.split()
    if tokens and all(t in TOKEN_STOPWORDS for t in tokens):
        return "3", "all-stopword fragment"

    return None, ""


# ---------------------------------------------------------------------------
# Pillar guess — subword overlap against a frozen seed dict.
#
# Inlined here (not imported from esg_keywords.py) so the pruner has zero
# runtime dependency on the dict it is helping to replace. The seed is a
# snapshot of the legacy hand-written dict; it is used *only* as a hint
# for the human reviewer and is not propagated into the final dictionary.
# ---------------------------------------------------------------------------

_SEED_PILLARS: dict[str, list[str]] = {
    "E": [
        "phát thải", "khí nhà kính", "khí thải", "carbon", "biến đổi khí hậu",
        "trung hòa carbon", "net zero", "năng lượng tái tạo", "năng lượng mặt trời",
        "điện mặt trời", "điện gió", "tiết kiệm năng lượng", "hiệu suất năng lượng",
        "tiêu thụ năng lượng", "tiết kiệm nước", "nước thải", "xử lý nước",
        "tài nguyên nước", "tiêu thụ nước", "khai thác nước", "chất thải",
        "tái chế", "tái sử dụng", "kinh tế tuần hoàn", "phân loại rác",
        "rác thải nhựa", "chất thải nguy hại", "nguyên vật liệu tái chế",
        "đa dạng sinh học", "bảo tồn", "rừng", "môi trường", "bảo vệ môi trường",
        "thân thiện môi trường", "phát triển bền vững", "bền vững", "sinh thái",
    ],
    "S": [
        "người lao động", "nhân viên", "đào tạo", "bồi dưỡng", "tuyển dụng",
        "phúc lợi", "lương thưởng", "thu nhập bình quân", "an toàn lao động",
        "vệ sinh lao động", "an toàn vệ sinh lao động", "tai nạn lao động",
        "bệnh nghề nghiệp", "phòng cháy chữa cháy", "bình đẳng giới", "đa dạng",
        "phụ nữ", "nữ giới", "lao động nữ", "phân biệt đối xử", "quyền con người",
        "công đoàn", "lao động trẻ em", "lao động cưỡng bức", "cộng đồng",
        "trách nhiệm xã hội", "an sinh xã hội", "từ thiện", "tài trợ", "ủng hộ",
        "thiện nguyện", "đóng góp xã hội", "an toàn sản phẩm", "chất lượng sản phẩm",
        "khách hàng", "bảo mật thông tin", "quyền riêng tư", "chuỗi cung ứng",
        "nhà cung cấp",
    ],
    "G": [
        "quản trị", "quản trị công ty", "quản trị doanh nghiệp",
        "hội đồng quản trị", "ban kiểm soát", "ban điều hành", "cổ đông",
        "đại hội đồng cổ đông", "minh bạch", "công bố thông tin", "kiểm toán",
        "kiểm soát nội bộ", "quản trị rủi ro", "quản lý rủi ro",
        "đạo đức kinh doanh", "bộ quy tắc ứng xử", "chống tham nhũng", "hối lộ",
        "xung đột lợi ích", "tuân thủ", "tuân thủ pháp luật", "thù lao",
    ],
}


def _seed_terms_by_pillar() -> dict[str, list[str]]:
    return {p: [normalize(k) for k in kws] for p, kws in _SEED_PILLARS.items()}


def guess_pillar(keyword: str, seed: dict[str, list[str]] | None = None) -> str:
    """Return 'E' / 'S' / 'G' / '?' based on token overlap with the seed dict."""
    if seed is None:
        seed = _seed_terms_by_pillar()
    norm = normalize(keyword)
    tokens = set(norm.split())
    if not tokens:
        return "?"
    scores: dict[str, int] = {}
    for pillar, terms in seed.items():
        score = 0
        for t in terms:
            t_tokens = set(t.split())
            if t in norm or norm in t:
                score += 3
            else:
                score += len(tokens & t_tokens)
        scores[pillar] = score
    best = max(scores, key=lambda p: scores[p])
    if scores[best] == 0:
        return "?"
    # Tie between pillars → "?"
    top_count = sum(1 for p in scores if scores[p] == scores[best])
    if top_count > 1:
        return "?"
    return best
