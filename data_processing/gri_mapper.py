"""Map Vietnamese ESG candidate sentences to GRI disclosures via multilingual embeddings.

Reads the auto-extracted taxonomy from data/processed/gri_taxonomy/disclosures.json
(produced by gri_loader.py) and layers hand-curated Vietnamese glosses from
data_processing/vi_glosses.json on top. Each disclosure's embedding text combines
EN title + EN overview/requirements + VN title + VN keywords, so the LaBSE model
can match Vietnamese sentences to the right GRI code without any translation step.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np

_TAXONOMY_PATH = Path(__file__).resolve().parents[1] / "data" / "processed" / "gri_taxonomy" / "disclosures.json"
_GLOSSES_PATH = Path(__file__).with_name("vi_glosses.json")
_DEFAULT_MODEL = "sentence-transformers/LaBSE"

# Disclosures from superseded standards are skipped — including them would
# double-count topics that the new standard already covers.
_DROP_SUPERSEDED = True


@dataclass(frozen=True)
class GRIMatch:
    code: str            # e.g. "305-1"
    standard_code: str   # e.g. "305"
    pillar: str
    title_en: str
    title_vi: str
    score: float


def _load_glosses(path: Path = _GLOSSES_PATH) -> dict[str, dict]:
    with open(path, encoding="utf-8") as f:
        return json.load(f)["glosses"]


def _load_disclosures(path: Path = _TAXONOMY_PATH) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _build_embedding_text(d: dict, gloss: dict | None) -> str:
    """Concatenate the fields LaBSE should see for this disclosure.
    Truncates each field to keep total length bounded (LaBSE has 512-token limit).
    """
    title_en = d.get("title", "")
    # Use the first ~600 chars of requirements (most disclosure-defining); fall
    # back to overview if requirements is empty.
    body_en = (d.get("requirements") or d.get("overview") or "")[:600]
    title_vi = (gloss or {}).get("title_vi", "")
    keywords_vi = " ".join((gloss or {}).get("keywords_vi", []))
    parts = [title_en, body_en, title_vi, keywords_vi]
    return ". ".join(p for p in parts if p)


@lru_cache(maxsize=1)
def _load_model(name: str = _DEFAULT_MODEL):
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer(name)


@lru_cache(maxsize=1)
def _build_index() -> tuple[list[dict], np.ndarray]:
    """Embed all (non-superseded) GRI disclosures once."""
    disclosures = _load_disclosures()
    if _DROP_SUPERSEDED:
        disclosures = [d for d in disclosures if not d.get("superseded_by")]
    glosses = _load_glosses()
    model = _load_model()
    texts = [_build_embedding_text(d, glosses.get(d["standard_code"])) for d in disclosures]
    matrix = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
    return disclosures, np.asarray(matrix, dtype=np.float32)


def map_sentences(
    sentences: list[str],
    top_k: int = 3,
    min_score: float = 0.45,
    batch_size: int = 64,
) -> list[list[GRIMatch]]:
    """For each sentence, return up to `top_k` GRI matches with cosine ≥ min_score."""
    if not sentences:
        return []
    disclosures, gri_matrix = _build_index()
    glosses = _load_glosses()
    model = _load_model()
    sent_vecs = model.encode(
        sentences,
        normalize_embeddings=True,
        batch_size=batch_size,
        show_progress_bar=False,
    )
    sent_vecs = np.asarray(sent_vecs, dtype=np.float32)
    sims = sent_vecs @ gri_matrix.T

    results: list[list[GRIMatch]] = []
    for row in sims:
        idxs = np.argsort(-row)[:top_k]
        matches: list[GRIMatch] = []
        for i in idxs:
            score = float(row[i])
            if score < min_score:
                continue
            d = disclosures[i]
            title_vi = (glosses.get(d["standard_code"]) or {}).get("title_vi", "")
            matches.append(GRIMatch(
                code=d["code"],
                standard_code=d["standard_code"],
                pillar=d["pillar"],
                title_en=d["title"],
                title_vi=title_vi,
                score=score,
            ))
        results.append(matches)
    return results
