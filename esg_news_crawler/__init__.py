"""ESG news crawler.

Crawls Vietnamese news for the companies in ``company_annual_report.xlsx`` and
emits sentence-split JSONL that matches the annual-report classifier path
(``source_pdf, page, sentence_index, text`` + news metadata).

No relevance / ESG filtering is done here on purpose — a downstream model decides
what to keep. The ESG / controversy keywords are used only to *retrieve* the rare
relevant articles that a bare ticker search would bury.
"""
