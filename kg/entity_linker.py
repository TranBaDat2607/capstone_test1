"""
kg/entity_linker.py
Entity deduplication and linking for the ESG Greenwashing Detection pipeline.

The linker normalises company names (lowercase, strip punctuation, Vietnamese
diacritic folding) and uses ``difflib.SequenceMatcher`` for fuzzy string
similarity so that, for example, "FPT Corp." and "Công ty FPT" are recognised
as the same entity without external ML dependencies.

Typical usage::

    from kg.graph_store import KnowledgeGraph
    from kg.entity_linker import EntityLinker

    kg = KnowledgeGraph()
    linker = EntityLinker(kg)

    existing_id = linker.find_existing_company("FPT Corporation")
    if existing_id:
        print("Found:", existing_id)
    else:
        node_id = linker.link_entity("COMP_NEW", "Company", {"name": "FPT Corp"})
        kg.add_node(node_id, "Company", {"name": "FPT Corp"})
"""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
from typing import Optional

from kg.graph_store import KnowledgeGraph


# ---------------------------------------------------------------------------
# Vietnamese diacritic normalisation table
# ---------------------------------------------------------------------------
# Maps common Vietnamese precomposed characters that may survive NFKD
# normalisation to their ASCII equivalents.  This list covers the most
# frequent characters seen in ESG company names.

_VIET_CHAR_MAP: dict[str, str] = {
    "đ": "d",
    "Đ": "d",
    "ă": "a",
    "â": "a",
    "ê": "e",
    "ô": "o",
    "ơ": "o",
    "ư": "u",
    "Ă": "a",
    "Â": "a",
    "Ê": "e",
    "Ô": "o",
    "Ơ": "o",
    "Ư": "u",
}

# Compiled regex for non-alphanumeric characters (whitespace kept for
# subsequent split-and-rejoin normalisation)
_NON_ALNUM_RE: re.Pattern[str] = re.compile(r"[^\w\s]", re.UNICODE)

# Common Vietnamese corporate suffixes to strip before comparison
_CORP_SUFFIXES: tuple[str, ...] = (
    "corporation",
    "corp",
    "company",
    "co",
    "ltd",
    "limited",
    "joint stock",
    "jsc",
    "group",
    "holdings",
    "holding",
    "cong ty",
    "tap doan",
    "tnhh",
    "co phan",
)


class EntityLinker:
    """Fuzzy-match entity linker backed by a :class:`~kg.graph_store.KnowledgeGraph`.

    Args:
        kg: The knowledge graph to search for existing nodes.
        similarity_threshold: Minimum SequenceMatcher ratio required to
            consider two names a match (default: 0.82).
    """

    def __init__(
        self,
        kg: KnowledgeGraph,
        similarity_threshold: float = 0.82,
    ) -> None:
        self._kg: KnowledgeGraph = kg
        self.similarity_threshold: float = similarity_threshold

        # Internal cache: normalised_name -> node_id
        # Populated lazily from the KG on first call to find_existing_company
        self._name_cache: dict[str, str] = {}
        self._ticker_cache: dict[str, str] = {}
        self._cache_valid: bool = False

    # ------------------------------------------------------------------
    # Cache management
    # ------------------------------------------------------------------

    def _rebuild_cache(self) -> None:
        """Rebuild the normalised-name and ticker lookup caches from the KG."""
        self._name_cache.clear()
        self._ticker_cache.clear()

        for node in self._kg.get_nodes_by_type("Company"):
            node_id: str = node["node_id"]
            props: dict = node.get("properties", {})

            name: str = props.get("name", "")
            if name:
                norm = self.normalize_company_name(name)
                if norm:
                    self._name_cache[norm] = node_id

            ticker: str = props.get("ticker", "")
            if ticker:
                self._ticker_cache[ticker.upper().strip()] = node_id

        self._cache_valid = True

    def invalidate_cache(self) -> None:
        """Force the name/ticker caches to be rebuilt on the next lookup."""
        self._cache_valid = False

    # ------------------------------------------------------------------
    # Normalisation
    # ------------------------------------------------------------------

    def normalize_company_name(self, name: str) -> str:
        """Return a canonical, ASCII-folded form of *name* for comparison.

        Steps applied:
        1. Replace Vietnamese-specific characters with ASCII equivalents.
        2. Apply Unicode NFKD decomposition and strip combining marks.
        3. Lowercase.
        4. Remove punctuation (keep alphanumerics and spaces).
        5. Strip common corporate suffixes.
        6. Collapse whitespace.

        Args:
            name: Raw company name string.

        Returns:
            Normalised name string (may be empty for degenerate inputs).
        """
        if not name or not name.strip():
            return ""

        result: str = name.strip()

        # Step 1: Replace Vietnamese-specific characters
        for viet_char, ascii_char in _VIET_CHAR_MAP.items():
            result = result.replace(viet_char, ascii_char)

        # Step 2: NFKD decomposition + drop combining marks
        result = unicodedata.normalize("NFKD", result)
        result = "".join(
            ch for ch in result if unicodedata.category(ch) != "Mn"
        )

        # Step 3: Lowercase
        result = result.lower()

        # Step 4: Remove punctuation (keep alphanumerics and whitespace)
        result = _NON_ALNUM_RE.sub(" ", result)

        # Step 5: Strip common corporate suffixes (whole-word match)
        tokens: list[str] = result.split()
        filtered: list[str] = []
        i = 0
        while i < len(tokens):
            # Try two-word suffixes first
            two_word = " ".join(tokens[i : i + 2])
            if two_word in _CORP_SUFFIXES:
                i += 2
                continue
            if tokens[i] in _CORP_SUFFIXES:
                i += 1
                continue
            filtered.append(tokens[i])
            i += 1
        result = " ".join(filtered)

        # Step 6: Collapse whitespace
        result = " ".join(result.split())

        return result

    # ------------------------------------------------------------------
    # Look-up
    # ------------------------------------------------------------------

    def find_existing_company(
        self,
        name: str,
        ticker: Optional[str] = None,
    ) -> Optional[str]:
        """Search the KG for a Company node matching *name* (and optionally *ticker*).

        Lookup order:
        1. Exact ticker match (if *ticker* is provided).
        2. Exact normalised-name match.
        3. Fuzzy normalised-name match above ``similarity_threshold``.

        Args:
            name:   Company name to search for.
            ticker: Optional stock ticker symbol.

        Returns:
            The ``node_id`` of the best-matching Company node, or ``None`` if
            no match meets the threshold.
        """
        if not self._cache_valid:
            self._rebuild_cache()

        # 1. Exact ticker match
        if ticker:
            ticker_upper = ticker.upper().strip()
            if ticker_upper in self._ticker_cache:
                return self._ticker_cache[ticker_upper]

        normalised_query = self.normalize_company_name(name)
        if not normalised_query:
            return None

        # 2. Exact normalised-name match
        if normalised_query in self._name_cache:
            return self._name_cache[normalised_query]

        # 3. Fuzzy match — find highest-scoring candidate
        best_id: Optional[str] = None
        best_ratio: float = 0.0

        for norm_name, node_id in self._name_cache.items():
            ratio: float = SequenceMatcher(
                None, normalised_query, norm_name
            ).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best_id = node_id

        if best_ratio >= self.similarity_threshold:
            return best_id

        return None

    # ------------------------------------------------------------------
    # Link helper
    # ------------------------------------------------------------------

    def link_entity(
        self,
        entity_id: str,
        entity_type: str,
        properties: dict,
    ) -> str:
        """Resolve *entity_id* against existing KG nodes.

        For Company entities the name-based lookup is used to detect
        duplicates.  For all other entity types the provided *entity_id* is
        returned as-is (the caller is responsible for adding the node).

        Args:
            entity_id:   Proposed node ID for the entity.
            entity_type: Ontology type of the entity (e.g. ``"Company"``).
            properties:  Entity properties dict.

        Returns:
            The ``node_id`` to use — either an existing duplicate's ID (for
            Company entities) or *entity_id* unchanged.
        """
        if entity_type == "Company":
            name: str = properties.get("name", "")
            ticker: Optional[str] = properties.get("ticker")
            existing_id = self.find_existing_company(name, ticker)
            if existing_id is not None:
                return existing_id

        # For non-Company types or when no match is found, use the given ID
        return entity_id

    # ------------------------------------------------------------------
    # Bulk helpers
    # ------------------------------------------------------------------

    def similarity(self, a: str, b: str) -> float:
        """Return the normalised string similarity ratio between *a* and *b*.

        Both strings are normalised before comparison.

        Args:
            a: First string.
            b: Second string.

        Returns:
            Float in [0.0, 1.0]; higher means more similar.
        """
        norm_a = self.normalize_company_name(a)
        norm_b = self.normalize_company_name(b)
        if not norm_a or not norm_b:
            return 0.0
        return SequenceMatcher(None, norm_a, norm_b).ratio()

    def find_all_similar_companies(
        self,
        name: str,
        min_similarity: float | None = None,
    ) -> list[dict]:
        """Return all Company nodes whose name is similar to *name*.

        Args:
            name:           Query company name.
            min_similarity: Override the instance-level threshold for this
                            call.  Defaults to ``self.similarity_threshold``.

        Returns:
            List of dicts sorted by descending similarity score, each with
            keys ``node_id``, ``similarity``, ``properties``.
        """
        if not self._cache_valid:
            self._rebuild_cache()

        threshold = (
            min_similarity
            if min_similarity is not None
            else self.similarity_threshold
        )
        normalised_query = self.normalize_company_name(name)
        if not normalised_query:
            return []

        results: list[dict] = []
        for norm_name, node_id in self._name_cache.items():
            ratio: float = SequenceMatcher(
                None, normalised_query, norm_name
            ).ratio()
            if ratio >= threshold:
                node = self._kg.get_node(node_id)
                results.append(
                    {
                        "node_id": node_id,
                        "similarity": round(ratio, 4),
                        "properties": node.get("properties", {}) if node else {},
                    }
                )

        results.sort(key=lambda x: x["similarity"], reverse=True)
        return results
