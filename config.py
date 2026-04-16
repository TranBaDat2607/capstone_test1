"""
config.py
Central configuration for the ESG Greenwashing Detection pipeline.

All tuneable parameters, paths, and environment-variable bindings live here.
Import with:
    from config import Config
"""

from __future__ import annotations

import os
from pathlib import Path

# Load .env file if present (python-dotenv optional)
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env")
except ImportError:
    pass


class Config:
    """Static configuration container for the ESG Greenwashing Detection pipeline.

    Attributes are class-level constants so callers can reference them without
    instantiation (``Config.LLM_MODEL``), but the class may also be instantiated
    if a per-run override pattern is desired in the future.
    """

    # ------------------------------------------------------------------
    # LLM / API settings
    # ------------------------------------------------------------------

    #: Which LLM backend to use.  Supported values: "anthropic", "google".
    LLM_PROVIDER: str = "google"

    #: Anthropic API key — read from environment, falls back to empty string.
    ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")

    #: OpenAI API key — read from environment, falls back to empty string.
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")

    #: Google AI (Gemini) API key — read from environment.
    GOOGLE_AI_API_KEY: str = os.getenv("GOOGLE_AI_API_KEY", "")

    #: Default model identifier sent to the LLM provider.
    LLM_MODEL: str = "gemini-2.0-flash"

    # ------------------------------------------------------------------
    # Neo4j / Graph-store settings
    # ------------------------------------------------------------------

    #: Bolt URI for Neo4j.
    NEO4J_URI: str = os.getenv("NEO4J_URI", "bolt://localhost:7687")

    #: Neo4j username.
    NEO4J_USER: str = os.getenv("NEO4J_USER", "neo4j")

    #: Neo4j password.
    NEO4J_PASSWORD: str = os.getenv("NEO4J_PASSWORD", "password")

    #: When False the pipeline uses an in-memory NetworkX graph instead of Neo4j.
    USE_NEO4J: bool = False

    # ------------------------------------------------------------------
    # File-system paths
    # ------------------------------------------------------------------

    #: Root directory of the project (directory that contains this file).
    BASE_DIR: Path = Path(__file__).parent

    #: Directory containing ontology schema and sample-instance JSON files.
    ONTOLOGY_DIR: Path = BASE_DIR / "ontology"

    #: Directory containing crawled news articles.
    CRAWL_NEWS_DIR: Path = BASE_DIR / "data" / "raw" / "crawl_data_news"

    #: Directory containing crawled PDF/report files.
    CRAWL_PDF_DIR: Path = BASE_DIR / "data" / "raw" / "crawled_annual_report"

    #: Directory where pipeline output artefacts are written.
    OUTPUT_DIR: Path = BASE_DIR / "output"

    #: Path to the sample-instances JSON used for development and testing.
    SAMPLE_INSTANCES_PATH: Path = ONTOLOGY_DIR / "sample_instances.json"

    #: Path to the ontology schema JSON.
    ONTOLOGY_SCHEMA_PATH: Path = ONTOLOGY_DIR / "ontology_schema.json"

    # ------------------------------------------------------------------
    # Graph-traversal parameters
    # ------------------------------------------------------------------

    #: Maximum hop depth when exploring the knowledge graph.
    MAX_GRAPH_DEPTH: int = 3

    #: Number of top-scoring paths returned by path-ranking routines.
    TOP_K_PATHS: int = 5

    # ------------------------------------------------------------------
    # Reinforcement-learning / iterative-reasoning parameters
    # ------------------------------------------------------------------

    #: Maximum number of RL reasoning iterations before forcing a conclusion.
    #: Kept low (2) to stay within free-tier Gemini quota.
    RL_MAX_ITERATIONS: int = 2

    #: Minimum cumulative reward required to accept an intermediate conclusion.
    RL_MIN_REWARD_THRESHOLD: float = 0.6

    # ------------------------------------------------------------------
    # Temporal-analysis parameters
    # ------------------------------------------------------------------

    #: Sliding window (in years) used when comparing time-series ESG metrics.
    TEMPORAL_WINDOW_YEARS: int = 2

    # ------------------------------------------------------------------
    # Greenwashing-detection thresholds
    # ------------------------------------------------------------------

    #: Fraction of mandatory disclosure categories that must be present;
    #: if coverage falls below this value the company is flagged for silence risk.
    SILENCE_COVERAGE_THRESHOLD: float = 0.3

    #: Trust scores *strictly below* this value are classified as **High** greenwashing risk.
    GREENWASHING_HIGH_THRESHOLD: float = 0.4

    #: Trust scores at-or-above HIGH but *strictly below* this value are classified
    #: as **Medium** greenwashing risk.  Scores at-or-above this value are **Low** risk.
    GREENWASHING_MEDIUM_THRESHOLD: float = 0.7

    # ------------------------------------------------------------------
    # Knowledge-graph edge-type classification
    # ------------------------------------------------------------------

    #: Edge types that *support* an ESG claim (positive evidence).
    PRO_EDGE_TYPES: list[str] = [
        "supported_by",
        "has_emission",
        "complies_with",
        "targets_reduction",
        "invests_in",
    ]

    #: Edge types that *contradict* or *weaken* an ESG claim (negative evidence).
    ANTI_EDGE_TYPES: list[str] = [
        "contradicted_by",
        "violates",
    ]

    # ------------------------------------------------------------------
    # Mandatory disclosure categories per regulation
    # ------------------------------------------------------------------

    #: Maps a regulation node ID to the list of ESG metric categories that
    #: companies subject to that regulation must disclose.
    MANDATORY_DISCLOSURE_CATEGORIES: dict[str, list[str]] = {
        # TT08/2026/TT-BTC — comprehensive ESG disclosure (effective 2026-02-03)
        "REG_TT08_2026": [
            "Emissions",
            "Energy",
            "Water",
            "Waste",
            "Employment",
            "Health_Safety",
            "Board_Governance",
            "Anti_corruption",
            "Transparency",
        ],
        # TT96/2020/TT-BTC — basic sustainability disclosure (effective 2021-01-01)
        "REG_TT96_2020": [
            "Emissions",
            "Energy",
            "Employment",
            "Board_Governance",
        ],
    }

    # ------------------------------------------------------------------
    # Convenience helpers
    # ------------------------------------------------------------------

    @classmethod
    def ensure_output_dir(cls) -> Path:
        """Create ``OUTPUT_DIR`` if it does not yet exist and return the path."""
        cls.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        return cls.OUTPUT_DIR

    @classmethod
    def greenwashing_risk_label(cls, trust_score: float) -> str:
        """Map a numeric trust score to a human-readable greenwashing risk label.

        Args:
            trust_score: A float in [0, 1] produced by the scoring module.

        Returns:
            One of ``"High"``, ``"Medium"``, or ``"Low"``.
        """
        if trust_score < cls.GREENWASHING_HIGH_THRESHOLD:
            return "High"
        if trust_score < cls.GREENWASHING_MEDIUM_THRESHOLD:
            return "Medium"
        return "Low"
