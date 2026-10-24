"""Deterministic relevance ranking service for evidence items."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Optional

from models.schemas import EvidenceItem, EvidenceType

# Stop words to remove from query tokenization
_STOP_WORDS = frozenset(
    {
        "a", "an", "the", "and", "or", "in", "of", "to", "for",
        "with", "on", "at", "from", "by", "is", "are", "was",
        "were", "be", "been", "being", "have", "has", "had",
        "do", "does", "did", "will", "would", "could", "should",
        "may", "might", "its", "it", "this", "that", "these",
        "those", "as", "not", "no", "but", "if", "so", "than",
    }
)

# Evidence type weights (0.0 – 1.0)
_EVIDENCE_WEIGHTS: dict[EvidenceType, float] = {
    EvidenceType.randomized_controlled_trial: 1.0,
    EvidenceType.clinical: 1.0,
    EvidenceType.systematic_review: 0.95,
    EvidenceType.observational: 0.85,
    EvidenceType.animal: 0.70,
    EvidenceType.cellular: 0.60,
    EvidenceType.biochemical: 0.55,
    EvidenceType.computational: 0.40,
    EvidenceType.literature_review: 0.50,
    EvidenceType.case_report: 0.60,
    EvidenceType.regulatory: 0.45,
    EvidenceType.editorial: 0.30,
    EvidenceType.correction_or_retraction: 0.30,
    EvidenceType.AI_hypothesis: 0.20,
    EvidenceType.other: 0.35,
}

_CURRENT_YEAR = datetime.now().year


def tokenize_query(query: str) -> list[str]:
    """Tokenize a query string to lowercase terms, removing stop words."""
    tokens = re.findall(r"\b[a-z0-9]+\b", query.lower())
    return [t for t in tokens if t not in _STOP_WORDS and len(t) > 1]


def score_components(item: EvidenceItem, query_terms: list[str]) -> dict:
    """Return every part of a relevance score, so a reason can name each one.

    The parts are what score_item combines; exposing them keeps the "why is this
    here" text derived from the same arithmetic rather than a second guess.
    """
    title_lower = (item.title or "").lower()
    abstract_lower = (item.abstract or "").lower()

    title_terms = [
        term for term in query_terms
        if re.search(r"\b" + re.escape(term) + r"\b", title_lower)
    ]
    abstract_terms = [
        term for term in query_terms
        if re.search(r"\b" + re.escape(term) + r"\b", abstract_lower)
    ]
    title_score = min(len(title_terms) * 0.3, 0.6)
    abstract_score = min(len(abstract_terms) * 0.15, 0.3)

    recency_score = 0.0
    age: Optional[int] = None
    if item.year is not None:
        age = _CURRENT_YEAR - item.year
        if age <= 2:
            recency_score = 0.1
        elif age <= 5:
            recency_score = 0.05

    evidence_weight = _EVIDENCE_WEIGHTS.get(item.evidence_type, 0.5)
    score = min(max((title_score + abstract_score) * evidence_weight + recency_score, 0.0), 1.0)
    return {
        "title_terms": title_terms,
        "abstract_terms": abstract_terms,
        "title_score": title_score,
        "abstract_score": abstract_score,
        "recency_score": recency_score,
        "age_years": age,
        "evidence_weight": evidence_weight,
        "score": score,
    }


def score_item(item: EvidenceItem, query_terms: list[str]) -> float:
    """Score an EvidenceItem against a list of query terms.

    Returns a float in [0.0, 1.0].
    """
    if not query_terms:
        return 0.0
    return score_components(item, query_terms)["score"]
