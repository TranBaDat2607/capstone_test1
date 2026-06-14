# -*- coding: utf-8 -*-
"""Free search channels (no API keys): Google News RSS, Bing, DuckDuckGo.

Each module exposes ``search(fetcher, query, num=..., since_years=...) -> list[dict]``
where every dict is ``{"url", "title", "channel"}``.
"""
