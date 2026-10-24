"""Literature views: four orderings of the retrieved records, each with its rule shown.

A view is a sort rule over fields the sources report, not a verdict on the
science. No quality score is computed here: `relevance_score` orders the
"most relevant" list and is not presented as a measure of how trustworthy a
paper is, and "strongest evidence" ranks the study design the source states,
which is the weakest kind of claim the ordering can honestly make.
"""

from __future__ import annotations

from typing import Optional

from models.schemas import (
    EvidenceDeduplication,
    EvidenceItem,
    EvidenceType,
    LiteratureExclusion,
    LiteratureFacet,
    LiteratureFilters,
    LiteratureView,
    LiteratureViewResult,
    RankReason,
)
from services.evidence_normalizer import report_from_provenance
from services.relevance_ranker import score_components, tokenize_query
from utils.dates import sort_key

# Study designs describing work in people, and those that do not, as the source's
# own publication types classify them. A record the source leaves unclassified
# belongs to neither, and the scope filter says so instead of guessing.
_CLINICAL_DESIGNS = frozenset(
    {
        EvidenceType.randomized_controlled_trial,
        EvidenceType.clinical,
        EvidenceType.systematic_review,
        EvidenceType.observational,
        EvidenceType.case_report,
    }
)
_PRECLINICAL_DESIGNS = frozenset(
    {
        EvidenceType.animal,
        EvidenceType.cellular,
        EvidenceType.biochemical,
        EvidenceType.computational,
    }
)

# Strongest design first. A correction or retraction is last because it reports
# on evidence rather than being evidence of its own; it is never removed.
_DESIGN_LADDER: list[EvidenceType] = [
    EvidenceType.randomized_controlled_trial,
    EvidenceType.systematic_review,
    EvidenceType.clinical,
    EvidenceType.observational,
    EvidenceType.case_report,
    EvidenceType.animal,
    EvidenceType.cellular,
    EvidenceType.biochemical,
    EvidenceType.computational,
    EvidenceType.regulatory,
    EvidenceType.literature_review,
    EvidenceType.editorial,
    EvidenceType.correction_or_retraction,
]
_LADDER_INDEX = {design: rank for rank, design in enumerate(_DESIGN_LADDER)}

# Publication-type wording this view treats as a review or a guideline.
_REVIEW_NEEDLES = (
    "review",
    "meta-analysis",
    "meta analysis",
    "systematic",
    "pooled analysis",
    "network meta",
    "guideline",
    "consensus statement",
    "evidence summary",
)

_VIEW_LABELS: dict[LiteratureView, str] = {
    LiteratureView.most_relevant: "Most relevant",
    LiteratureView.latest: "Latest",
    LiteratureView.strongest_evidence: "Strongest evidence",
    LiteratureView.reviews_guidelines: "Reviews & guidelines",
}

_VIEW_RULES: dict[LiteratureView, str] = {
    LiteratureView.most_relevant: (
        "Query words matched in the title count three times what the same word in "
        "the abstract counts, the design the source reports scales that match, and "
        "a record published within two years adds 0.1. Nothing here judges whether "
        "a study was well run."
    ),
    LiteratureView.latest: (
        "Ordered by the publication date each source states, most recent first, "
        "with a partly stated date sorted at the start of the year or month it "
        "names. A database's indexing date is shown beside the record and is never "
        "used for this ordering."
    ),
    LiteratureView.strongest_evidence: (
        "Ordered by the study design the source itself reports: randomized "
        "controlled trials first, then systematic reviews, other clinical and "
        "observational studies, then animal, cellular, biochemical and "
        "computational work. Records with the same design are ordered by "
        "publication date. This ranks designs, not individual papers: no paper is "
        "scored for how reliably it was conducted, and a notice about a record is "
        "listed last because it reports on evidence rather than being any."
    ),
    LiteratureView.reviews_guidelines: (
        "Keeps only records whose own reported publication types name a review, "
        "meta-analysis, guideline or consensus statement, then orders them by "
        "publication date. A record the source gives no review type for is not "
        "guessed at; how many were left out is stated above the list."
    ),
}


def build_view(
    items: list[EvidenceItem],
    query: str,
    view: LiteratureView = LiteratureView.most_relevant,
    filters: Optional[LiteratureFilters] = None,
    deduplication: Optional[EvidenceDeduplication] = None,
) -> LiteratureViewResult:
    """Filter and order retrieved records one way, and say how that was done."""
    filters = filters or LiteratureFilters()
    literature = [i for i in items if i.source_type == "literature"]
    non_literature = len(items) - len(literature)

    facets = build_facets(literature)
    kept, exclusions = _apply_filters(literature, filters, query)
    if non_literature:
        exclusions.insert(
            0,
            LiteratureExclusion(
                filter="source_type",
                label="records that are not publications",
                removed=non_literature,
                note=(
                    "Regulatory and trial records are shown in their own sections "
                    "and are not listed as literature."
                ),
            ),
        )

    ordered = _order(kept, query, view)
    for rank, item in enumerate(ordered, start=1):
        item.rank_reasons = _reasons(item, query, view, rank)
        item.view = view

    if deduplication is None:
        deduplication = report_from_provenance(literature)

    limitations = _limitations(view, kept, ordered, exclusions)
    return LiteratureViewResult(
        view=view,
        label=_VIEW_LABELS[view],
        rule=_VIEW_RULES[view],
        ordered_by=_ordered_by(view),
        items=ordered,
        records_received=len(literature),
        records_shown=len(ordered),
        exclusions=exclusions,
        facets=facets,
        deduplication=deduplication,
        limitations=limitations,
    )


def _ordered_by(view: LiteratureView) -> list[str]:
    if view == LiteratureView.most_relevant:
        return ["relevance to the query words", "as reported by the source"]
    if view == LiteratureView.latest:
        return ["publication date the source states", "title"]
    if view == LiteratureView.strongest_evidence:
        return ["study design the source reports", "publication date"]
    return ["reported review or guideline type", "publication date"]


def _apply_filters(
    items: list[EvidenceItem], filters: LiteratureFilters, query: str
) -> tuple[list[EvidenceItem], list[LiteratureExclusion]]:
    """Drop records a filter excludes, counting each so the UI can show why."""
    kept = list(items)
    exclusions: list[LiteratureExclusion] = []

    def apply(name: str, label: str, keep, note: Optional[str] = None) -> None:
        before = len(kept)
        survivor = [item for item in kept if keep(item)]
        if before and len(survivor) != before:
            exclusions.append(
                LiteratureExclusion(
                    filter=name, label=label, removed=before - len(survivor), note=note
                )
            )
        kept.clear()
        kept.extend(survivor)

    if filters.published_from or filters.published_to:
        low = sort_key(filters.published_from) if filters.published_from else (0, 0, 0)
        high = sort_key(filters.published_to) if filters.published_to else (9999, 12, 31)

        def in_range(item: EvidenceItem) -> bool:
            if not item.published_on and item.year is None:
                return False
            key = sort_key(item.published_on, item.year)
            return low <= key <= high

        apply(
            "published_on",
            f"publication date between {filters.published_from or 'any'} and "
            f"{filters.published_to or 'any'}",
            in_range,
            note=(
                "Records whose source states no publication date at all are left "
                "out of a date-filtered list; that is not the same as having no "
                "record in the range."
            ),
        )

    if filters.evidence_types:
        wanted = set(filters.evidence_types)
        apply(
            "evidence_type",
            "study design: " + ", ".join(t.value.replace("_", " ") for t in filters.evidence_types),
            lambda item: item.evidence_type in wanted,
            note=(
                "A record is in a class only when the source reported a "
                "publication type naming it; unclassified records match no class."
            ),
        )

    if filters.study_scope in ("clinical", "preclinical"):
        wanted = (
            _CLINICAL_DESIGNS
            if filters.study_scope == "clinical"
            else _PRECLINICAL_DESIGNS
        )
        apply(
            "study_scope",
            "clinical studies of people"
            if filters.study_scope == "clinical"
            else "preclinical work in animals, cells or models",
            lambda item: item.evidence_type in wanted,
            note=(
                "Classified from the publication type the source reported. Editorials, "
                "reviews, notices and records with no reported type are in neither "
                "scope, so they are removed by this filter rather than counted in one."
            ),
        )

    if filters.open_access is not None:
        wanted_open = filters.open_access
        apply(
            "open_access",
            "open access" if wanted_open else "not stated open access",
            lambda item: item.open_access is wanted_open,
            note=(
                "Only Europe PMC states an open-access flag. A record from a source "
                "that does not state one is removed by this filter, because "
                "'not stated' is not 'not open access'."
            ),
        )

    if filters.sources:
        wanted_sources = {s.strip().lower() for s in filters.sources if s.strip()}
        apply(
            "source",
            "source database: " + ", ".join(sorted(filters.sources)),
            lambda item: item.source.lower() in wanted_sources,
        )

    if filters.publication_types:
        needles = [p.strip().lower() for p in filters.publication_types if p.strip()]
        apply(
            "publication_type",
            "publication type: " + ", ".join(filters.publication_types),
            lambda item: any(
                needle in stated.lower()
                for stated in item.publication_types
                for needle in needles
            ),
            note=(
                "Matched against the publication-type strings the source itself "
                "reported, so a correction notice or editorial can be selected."
            ),
        )

    if filters.subtype_label:
        from services.disease_analytics import paper_names_label

        label = filters.subtype_label
        apply(
            "subtype",
            f"names the subtype “{label}” in its own wording",
            lambda item: paper_names_label(item, label),
            note=(
                "Matched on the paper's own title or abstract wording. A paper "
                "about the subtype that does not name it is not detected, and none "
                "being detected here does not mean none exists."
            ),
        )

    if filters.relevance_to_target is not None and filters.target_terms:
        wanted = filters.relevance_to_target

        def names_target(item: EvidenceItem) -> bool:
            text = f"{item.title or ''} {item.abstract or ''}".lower()
            return any(term.strip().lower() in text for term in filters.target_terms if term.strip())

        apply(
            "target",
            "names a retrieved target or mechanism"
            if wanted
            else "does not name a retrieved target or mechanism",
            names_target,
            note=(
                "Checked against the target names retrieved for this query. Wording "
                "in a title or abstract is not evidence that the study acted on that "
                "target."
            ),
        )

    return kept, exclusions


def _order(items: list[EvidenceItem], query: str, view: LiteratureView) -> list[EvidenceItem]:
    """Sort a copy of the records by one view's rule."""
    out = [item.model_copy() for item in items]
    if view == LiteratureView.most_relevant:
        terms = tokenize_query(query)
        for item in out:
            item.relevance_score = score_components(item, terms)["score"]
        out.sort(key=lambda i: (-i.relevance_score, -sort_key(i.published_on, i.year)[0], i.title or ""))
        return out
    if view == LiteratureView.latest:
        out.sort(
            key=lambda i: (
                -sort_key(i.published_on, i.year)[0],
                -sort_key(i.published_on, i.year)[1],
                -sort_key(i.published_on, i.year)[2],
                i.title or "",
            )
        )
        return out
    if view == LiteratureView.strongest_evidence:
        out.sort(
            key=lambda i: (
                _LADDER_INDEX.get(i.evidence_type, len(_LADDER_INDEX)),
                -sort_key(i.published_on, i.year)[0],
                i.title or "",
            )
        )
        return out
    reviews = [i for i in out if _review_types(i)]
    reviews.sort(
        key=lambda i: (
            0 if EvidenceType.systematic_review in (i.evidence_type,) else 1,
            -sort_key(i.published_on, i.year)[0],
            i.title or "",
        )
    )
    return reviews


def _review_types(item: EvidenceItem) -> list[str]:
    """The reported publication types naming a review, guideline or meta-analysis."""
    return [
        stated
        for stated in item.publication_types
        if any(needle in stated.lower() for needle in _REVIEW_NEEDLES)
    ]


def _reasons(
    item: EvidenceItem, query: str, view: LiteratureView, rank: int
) -> list[RankReason]:
    """State why this record sits where it does, from the fields the rule read."""
    reasons: list[RankReason] = []
    terms = tokenize_query(query)

    if view == LiteratureView.most_relevant and terms:
        parts = score_components(item, terms)
        if parts["title_terms"]:
            reasons.append(
                RankReason(
                    label="Title states " + ", ".join(f"“{t}”" for t in parts["title_terms"]),
                    source_field="title",
                )
            )
        if parts["abstract_terms"]:
            reasons.append(
                RankReason(
                    label="Abstract states " + ", ".join(f"“{t}”" for t in parts["abstract_terms"]),
                    source_field="abstract",
                )
            )
        if not parts["title_terms"] and not parts["abstract_terms"]:
            reasons.append(
                RankReason(
                    label="No query word appears in this record's title or abstract",
                    source_field="title",
                )
            )
        design = item.publication_types or [item.evidence_type.value.replace("_", " ")]
        reasons.append(
            RankReason(
                label="Study design the source reports scales this match: "
                + "; ".join(design),
                source_field="publication_types",
            )
        )
        if parts["recency_score"]:
            reasons.append(
                RankReason(
                    label=f"Published {item.year}, within "
                    f"{int(parts['age_years'])} year(s) of this retrieval",
                    source_field="year",
                )
            )

    if view == LiteratureView.latest:
        reasons.append(_date_reason(item))

    if view == LiteratureView.strongest_evidence:
        design = item.publication_types or [item.evidence_type.value.replace("_", " ")]
        position = _LADDER_INDEX.get(item.evidence_type)
        reasons.append(
            RankReason(
                label="Source reports this design: " + "; ".join(design)
                + (f" (position {position + 1} of {len(_LADDER_INDEX)} in this ordering)"
                   if position is not None else " (no design position: the source reported none)"),
                source_field="publication_types",
            )
        )
        reasons.append(
            RankReason(
                label=(
                    "Ordering of study designs as the sources report them. It is not "
                    "a score for how reliably this study was conducted."
                ),
                source_field="evidence_type",
            )
        )
        if item.published_on:
            reasons.append(_date_reason(item))

    if view == LiteratureView.reviews_guidelines:
        stated = _review_types(item)
        reasons.append(
            RankReason(
                label="Source labels this " + ("; ".join(stated) if stated else "a review by class, not by label"),
                source_field="publication_types",
            )
        )
        if item.published_on:
            reasons.append(_date_reason(item))

    if item.evidence_type == EvidenceType.correction_or_retraction:
        reasons.append(
            RankReason(
                label="The source reports this as a correction, retraction or notice "
                "about another record, not as primary evidence",
                source_field="publication_types",
            )
        )
    elif item.evidence_type == EvidenceType.editorial:
        reasons.append(
            RankReason(
                label="The source reports this as an editorial, comment, letter or news item",
                source_field="publication_types",
            )
        )

    if item.indexed_on:
        reasons.append(
            RankReason(
                label=f"Indexed by {item.source} on {item.indexed_on} "
                f"({item.indexed_field or 'indexing date'}) — an indexing date, not a publication date",
                source_field="indexed_on",
            )
        )
    if item.merged_records > 1:
        reasons.append(
            RankReason(
                label=f"One publication assembled from {item.merged_records} retrieved "
                f"record(s) from {', '.join(item.merged_sources or [item.source])}, matched "
                "on PMID, PMCID or DOI",
                source_field="merged_records",
            )
        )
    reasons.append(
        RankReason(label=f"Position {rank} in this view", source_field="view")
    )
    return reasons


def _date_reason(item: EvidenceItem) -> RankReason:
    if item.published_on:
        precision = item.published_precision or "year"
        stated = (
            f"Published {item.published_on}"
            if precision == "day"
            else f"Published {item.published_on} — the source states a {precision} only"
        )
        return RankReason(label=stated, source_field="published_on")
    if item.year is not None:
        return RankReason(
            label=f"Publication year {item.year} only; no fuller date reported",
            source_field="year",
        )
    return RankReason(
        label="No publication date reported, so this record sorts last on date",
        source_field="published_on",
    )


def build_facets(items: list[EvidenceItem]) -> list[LiteratureFacet]:
    """Count the retrieved records under each filter option, before filtering."""
    facets: list[LiteratureFacet] = []

    def count(field: str, values, stated_by_source: bool = True) -> None:
        tally: dict[str, int] = {}
        for value in values:
            if value:
                tally[value] = tally.get(value, 0) + 1
        for value, total in sorted(tally.items(), key=lambda kv: (-kv[1], kv[0])):
            facets.append(
                LiteratureFacet(
                    field=field, value=value, count=total,
                    stated_by_source=stated_by_source,
                )
            )

    count("source", [item.source for item in items])
    count("publication_type", [stated for item in items for stated in item.publication_types])
    count("evidence_type", [item.evidence_type.value.replace("_", " ") for item in items], False)
    count("open_access", ["open access" if item.open_access is True else
                          "not open access" if item.open_access is False else None
                          for item in items])
    count("year", [str(item.year) for item in items if item.year is not None])
    return facets


def _limitations(
    view: LiteratureView,
    kept: list[EvidenceItem],
    ordered: list[EvidenceItem],
    exclusions: list[LiteratureExclusion],
) -> list[str]:
    limits: list[str] = []
    if view == LiteratureView.reviews_guidelines:
        limits.append(
            f"{len(kept) - len(ordered)} of the records left after the other filters "
            "name no review, guideline or meta-analysis type and are not shown in this "
            "view. A paper that reviews a topic without the source labelling it that "
            "way cannot be detected."
        )
    no_date = sum(1 for item in ordered if not item.published_on and item.year is None)
    if no_date:
        limits.append(
            f"{no_date} record(s) carry no publication date from their source. They are "
            "listed by date with no date rather than given an invented one."
        )
    vague = sum(1 for item in ordered if item.published_precision in (None, "year"))
    if vague and view == LiteratureView.latest:
        limits.append(
            f"{vague} record(s) state a year only. A year-only record sorts at the start "
            "of that year, so it can appear below records published later in the same year."
        )
    if exclusions:
        limits.append(
            "Every filter above reports how many records it removed. A filter removes a "
            "record only for what its source states, so a filtered list describes this "
            "retrieval, not the literature."
        )
    limits.append(
        "These views order the records this search retrieved. No view computes a quality "
        "score, and no record's position says anything about how reliably it was conducted."
    )
    return limits
