"""Deterministic evidence-class aggregation for the dossier.

Counts records by the class of experiment the source itself reported. No numeric
score is computed and none is displayed: the volume of publications on a topic
does not make the evidence strong, so the panel reports what exists, states the
rule it used, and leaves the interpretation to the reader.

Registry trials are deliberately not counted here — the Clinical Development
section already reports them from the same ClinicalTrials.gov records, and
counting them twice would inflate the apparent evidence base.
"""

from __future__ import annotations

from collections import OrderedDict
from typing import Optional

from models.schemas import (
    EvidenceCategory,
    EvidenceItem,
    EvidenceStrength,
    StudyDesignCount,
)

# class key -> (label, the rule that placed a record here)
_CLASS_LABELS: "OrderedDict[str, tuple[str, str]]" = OrderedDict(
    (
        (
            "rct",
            (
                "Randomized controlled trials",
                "Source reported a publication type naming a randomized controlled trial.",
            ),
        ),
        (
            "systematic_review",
            (
                "Systematic reviews and meta-analyses",
                "Source reported a publication type naming a systematic review, meta-analysis or pooled analysis.",
            ),
        ),
        (
            "clinical_trial",
            (
                "Other clinical studies of patients",
                "Source reported a clinical trial or clinical study type without stating randomization.",
            ),
        ),
        (
            "observational",
            (
                "Human observational studies",
                "Source reported a cohort, case-control, cross-sectional, longitudinal, retrospective, prospective or observational study type.",
            ),
        ),
        (
            "case_report",
            (
                "Case reports and case series",
                "Source reported a case report or case series publication type.",
            ),
        ),
        (
            "animal",
            (
                "Animal and other in vivo preclinical studies",
                "Source reported an animal, in vivo or veterinary publication type.",
            ),
        ),
        (
            "cellular",
            (
                "Cellular, biochemical or in vitro work",
                "Source reported an in vitro, cell-line, biochemical or crystal-structure publication type.",
            ),
        ),
        (
            "computational",
            (
                "Computational and in silico studies",
                "Source reported a computational, modelling or simulation publication type.",
            ),
        ),
        (
            "review",
            (
                "Narrative reviews, guidelines and consensus statements",
                "Source reported a review, guideline or consensus publication type without a systematic method.",
            ),
        ),
        (
            "editorial",
            (
                "Editorials, comments, letters and news",
                "Source reported an editorial, comment, letter, interview or news publication type.",
            ),
        ),
        (
            "correction_or_retraction",
            (
                "Corrections, retractions and notices about a record",
                "Source reported an erratum, correction, retraction, withdrawal or expression of concern.",
            ),
        ),
        (
            "regulatory",
            (
                "Regulatory label text",
                "Passage quoted from an FDA drug label section, not a study.",
            ),
        ),
        (
            "unclassified",
            (
                "Not classified by the source metadata",
                "The source supplied no publication type this map recognises, so no class is assumed.",
            ),
        ),
    )
)

_CLASS_BY_EVIDENCE_TYPE: dict[str, str] = {
    "randomized_controlled_trial": "rct",
    "systematic_review": "systematic_review",
    "clinical": "clinical_trial",
    "observational": "observational",
    "case_report": "case_report",
    "animal": "animal",
    "cellular": "cellular",
    "biochemical": "cellular",
    "computational": "computational",
    "literature_review": "review",
    "editorial": "editorial",
    "correction_or_retraction": "correction_or_retraction",
    "regulatory": "regulatory",
    "AI_hypothesis": "unclassified",
    "other": "unclassified",
}

# Classes that describe a study of people, used only for the limitations text.
_HUMAN_CLASSES = {"rct", "systematic_review", "clinical_trial", "observational", "case_report"}


def _class_of(item: EvidenceItem) -> str:
    if item.source_type == "regulatory":
        return "regulatory"
    key = item.evidence_type.value if hasattr(item.evidence_type, "value") else str(item.evidence_type)
    return _CLASS_BY_EVIDENCE_TYPE.get(key, "unclassified")


def _record_label(item: EvidenceItem) -> str:
    """Title, identifier and the publication types the source actually reported."""
    title = (item.title or item.abstract or "Untitled record").strip()
    ident = item.id or item.url or "no identifier"
    reported = item.metadata.get("publication_types") if isinstance(item.metadata, dict) else None
    reported = [str(t) for t in (reported or []) if str(t).strip()]
    stated = "; ".join(reported) if reported else "no publication type reported"
    return f"{title[:160]} [{ident}] — source type: {stated}"


def compute_evidence_strength(evidence: list[EvidenceItem]) -> EvidenceStrength:
    """Group retrieved records into evidence classes with their sources.

    Every class count is one unit — a retrieved evidence record — and the unit is
    stated with the total, because the set mixes publications with label
    passages. Reporting "37" next to a literature table that says "25
    publications" without naming the difference is what makes a report look
    self-contradictory.
    """
    buckets: dict[str, list[EvidenceItem]] = {key: [] for key in _CLASS_LABELS}
    for item in evidence:
        buckets[_class_of(item)].append(item)

    categories = [
        EvidenceCategory(
            key=key,
            label=_CLASS_LABELS[key][0],
            criteria=_CLASS_LABELS[key][1],
            count=len(records),
            unit="label passage" if key == "regulatory" else "publication",
            records=[_record_label(r) for r in records],
        )
        for key, records in buckets.items()
    ]

    # Classes with no records are dropped; an empty bar is not a finding.
    populated = [c for c in categories if c.count]
    unclassified = len(buckets["unclassified"])
    regulatory = len(buckets["regulatory"])
    publications = len(evidence) - regulatory

    strength = EvidenceStrength(
        categories=populated,
        unclassified_count=unclassified,
        predominant_tier=_predominant(populated),
        limitations=_limitations(populated, unclassified),
        total_records=len(evidence),
        publication_records=publications,
        regulatory_passages=regulatory,
        mutually_exclusive=True,
        denominator=(
            f"{len(evidence)} retrieved evidence record(s) = "
            f"{publications} publication(s) + {regulatory} regulatory label "
            "passage(s). Each record is placed in exactly one class, so these "
            "counts are mutually exclusive and sum to that total. A label passage "
            "is not a publication."
        ),
        reconciles=sum(c.count for c in populated) == len(evidence),
        study_design_counts=_study_design_counts(evidence, publications),
    )
    strength.interpretation = _interpretation(strength)
    return strength


# Counts a narrative is allowed to quote. Each entry is (label, the substring a
# source-reported publication type must contain, or None for any record in these
# classes, the classes it may come from). A design count never spans more than
# one unit: these are all publications, so label passages cannot inflate them.
_DESIGN_FILTERS: tuple[tuple[str, Optional[str], frozenset[str]], ...] = (
    (
        "Randomized controlled trials",
        "randomi",
        frozenset({"rct"}),
    ),
    (
        "Real-world and observational studies of patients",
        None,
        frozenset({"observational"}),
    ),
    (
        "Systematic reviews and meta-analyses",
        None,
        frozenset({"systematic_review"}),
    ),
    (
        "Case reports and case series",
        None,
        frozenset({"case_report"}),
    ),
)


def _study_design_counts(
    evidence: list[EvidenceItem], publications: int
) -> list[StudyDesignCount]:
    """Counts a narrative may quote, each with the records behind it.

    Derived from the publication types the sources reported. A reader can open
    the listed records and recount them, which is more than a summary sentence
    offers, and the model is given these numbers so it never has to estimate one.
    """
    out: list[StudyDesignCount] = []
    for label, needle, keys in _DESIGN_FILTERS:
        matched = [
            item
            for item in evidence
            if item.source_type == "literature"
            and _class_of(item) in keys
            and (
                needle is None
                or any(needle in (t or "").casefold() for t in item.publication_types)
            )
        ]
        basis = (
            f"source-reported publication type contains \"{needle}\""
            if needle
            else "the class the source-reported publication type maps to"
        )
        out.append(
            StudyDesignCount(
                label=label,
                definition=(
                    f"A retrieved publication placed in \"{label}\" by {basis}. "
                    "Records the source gave no recognised publication type for "
                    "are not counted here, so this is what this retrieval found, "
                    "not what exists."
                ),
                count=len(matched),
                records=[_record_label(r) for r in matched],
                denominator=f"{publications} publication(s) retrieved",
            )
        )
    return out


def _predominant(categories: list[EvidenceCategory]) -> Optional[str]:
    """Name the class holding most records, ignoring the unclassified catch-all."""
    experimental = [c for c in categories if c.key != "unclassified"]
    if not experimental:
        return None
    top = max(experimental, key=lambda c: c.count)
    return top.key if top.count else None


def _interpretation(strength: EvidenceStrength) -> str:
    if not strength.categories:
        return (
            "None of the retrieved records carried publication-type metadata, so "
            "no class can be reported for them."
        )
    if strength.predominant_tier:
        label = _CLASS_LABELS[strength.predominant_tier][0]
        lead = f'The largest class in this retrieval is "{label}".'
    else:
        lead = "The retrieved records are unclassified."
    return (
        f"{lead} This is an automated grouping of the records this search "
        "retrieved, using only the publication types the sources reported. It "
        "counts records; it does not measure how reliable or conclusive they are."
    )


def _limitations(categories: list[EvidenceCategory], unclassified: int) -> list[str]:
    limits: list[str] = []
    keys = {c.key for c in categories}

    if not keys & {"rct", "clinical_trial", "systematic_review"}:
        limits.append(
            "No interventional clinical study was classified in this retrieval, so "
            "efficacy in patients cannot be inferred from it."
        )
    if not keys & _HUMAN_CLASSES:
        limits.append(
            "The retrieved set contains no classified human study, so findings here "
            "rest on non-human, secondary or regulatory records."
        )
    if keys & {"cellular", "computational", "animal"} and not keys & {
        "rct",
        "clinical_trial",
        "observational",
    }:
        limits.append(
            "Cellular, computational or animal records do not establish activity in "
            "people; the human evidence needed for that is absent from this set."
        )
    if unclassified:
        limits.append(
            f"{unclassified} record(s) carried no recognised publication type and are "
            "listed as unclassified rather than counted as evidence of any kind."
        )
    if keys & {"correction_or_retraction"}:
        limits.append(
            "Records under corrections and retractions are notices about other "
            "publications; they are separated here so they are not read as primary evidence."
        )
    limits.append(
        "Classification reads the publication-type metadata the source attached to the "
        "record. A record mislabelled at the source is mislabelled here too."
    )
    limits.append(
        "ClinicalTrials.gov studies are counted in the Clinical Development section from "
        "the registry records themselves, not here, so no trial is counted twice."
    )
    return limits
