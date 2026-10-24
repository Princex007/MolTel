"""Map source publication types onto the platform's evidence classes.

Classification only ever reads what the source itself reported in
PublicationTypeList (PubMed) or pubTypeList (Europe PMC). When nothing in that
list is understood, the record stays `other` — it is not quietly labelled a
review, because the source did not say it was one.
"""

from __future__ import annotations

from typing import Iterable, Optional

from models.schemas import EvidenceType

# Checked before the strength ranking below: a notice about the record outranks
# what the record claims to be, so retracted or corrected work is surfaced
# rather than counted as ordinary evidence.
_CORRECTION_NEEDLES = (
    "retract",
    "withdrawn publication",
    "expression of concern",
    "published erratum",
    "erratum",
    "correction",
    "corrected and republished",
)

# Strongest first; the first matching publication type wins.
_PUB_TYPE_MAP: tuple[tuple[str, EvidenceType], ...] = (
    ("meta-analysis", EvidenceType.systematic_review),
    ("pooled analysis", EvidenceType.systematic_review),
    ("network meta", EvidenceType.systematic_review),
    ("systematic review", EvidenceType.systematic_review),
    ("randomized controlled trial", EvidenceType.randomized_controlled_trial),
    ("randomised controlled trial", EvidenceType.randomized_controlled_trial),
    ("pragmatic clinical trial", EvidenceType.randomized_controlled_trial),
    ("controlled clinical trial", EvidenceType.clinical),
    ("clinical trial phase", EvidenceType.clinical),
    ("clinical study", EvidenceType.clinical),
    ("clinical trial", EvidenceType.clinical),
    ("case report", EvidenceType.case_report),
    ("case series", EvidenceType.case_report),
    ("observational study", EvidenceType.observational),
    ("cohort study", EvidenceType.observational),
    ("case-control study", EvidenceType.observational),
    ("cross-sectional study", EvidenceType.observational),
    ("longitudinal study", EvidenceType.observational),
    ("retrospective study", EvidenceType.observational),
    ("prospective study", EvidenceType.observational),
    ("dual agent research", EvidenceType.animal),
    ("multicenter study", EvidenceType.observational),
    ("animal", EvidenceType.animal),
    ("in vivo", EvidenceType.animal),
    ("veterinary", EvidenceType.animal),
    ("in vitro", EvidenceType.cellular),
    ("cell-based", EvidenceType.cellular),
    ("cell line", EvidenceType.cellular),
    ("biochemical", EvidenceType.biochemical),
    ("crystal structure", EvidenceType.biochemical),
    ("computational", EvidenceType.computational),
    ("modeling", EvidenceType.computational),
    ("simulation study", EvidenceType.computational),
    ("editorial", EvidenceType.editorial),
    ("comment", EvidenceType.editorial),
    ("letter", EvidenceType.editorial),
    ("interview", EvidenceType.editorial),
    ("news", EvidenceType.editorial),
    ("biographical portrait", EvidenceType.editorial),
    ("review", EvidenceType.literature_review),
    ("lecture", EvidenceType.literature_review),
    ("guideline", EvidenceType.literature_review),
    ("consensus statement", EvidenceType.literature_review),
)


def classify_publication_types(pub_types: Iterable[str]) -> Optional[EvidenceType]:
    """Return the evidence class implied by a list of reported publication types.

    Returns None when nothing matches, so the caller can leave the record
    unclassified instead of inventing a class for it.
    """
    normalized = [(t or "").strip().lower() for t in pub_types]
    normalized = [t for t in normalized if t]

    if any(any(needle in t for needle in _CORRECTION_NEEDLES) for t in normalized):
        return EvidenceType.correction_or_retraction

    for needle, evidence_type in _PUB_TYPE_MAP:
        if any(needle in t for t in normalized):
            return evidence_type
    return None
