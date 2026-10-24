"""Unit tests for the literature views and filters (spec §7).

Every record here is constructed in the test; no external API is called and no
model is asked to rank anything.
"""

from __future__ import annotations

from models.schemas import (
    EvidenceItem,
    EvidenceType,
    LiteratureFilters,
    LiteratureView,
)
from services.literature_view import build_view

_QUERY = "TRPC5 Alzheimer"


def _item(
    title: str,
    *,
    source: str = "PubMed",
    pmid: str | None = None,
    pmcid: str | None = None,
    doi: str | None = None,
    abstract: str = "",
    year: int | None = 2020,
    published_on: str | None = None,
    published_precision: str | None = None,
    indexed_on: str | None = None,
    indexed_field: str | None = None,
    evidence_type: EvidenceType = EvidenceType.other,
    publication_types: list[str] | None = None,
    open_access: bool | None = None,
    source_type: str = "literature",
) -> EvidenceItem:
    return EvidenceItem(
        source=source,
        source_type=source_type,
        id=pmid,
        pmid=pmid,
        pmcid=pmcid,
        doi=doi,
        title=title,
        abstract=abstract,
        year=year,
        published_on=published_on,
        published_precision=published_precision,
        indexed_on=indexed_on,
        indexed_field=indexed_field,
        evidence_type=evidence_type,
        publication_types=publication_types or [],
        open_access=open_access,
    )


def _labels(result) -> list[str]:
    return [item.title for item in result.items]


# --- Latest ---------------------------------------------------------------


def test_latest_view_orders_by_the_date_the_source_states():
    newest = _item("Newest", published_on="2024-06-02", published_precision="day")
    middle = _item("Middle", published_on="2023-01", published_precision="month")
    oldest = _item("Oldest", published_on="2019", published_precision="year")

    result = build_view([middle, oldest, newest], _QUERY, LiteratureView.latest)

    assert _labels(result) == ["Newest", "Middle", "Oldest"]
    assert result.label == "Latest"


def test_a_year_only_record_sorts_at_the_start_of_its_year_and_says_so():
    """Padding to January 1 is an ordering device, not a date the source gave."""
    jan = _item("Earlier in 2024", published_on="2024", published_precision="year")
    mar = _item("Later in 2024", published_on="2024-03-04", published_precision="day")

    result = build_view([mar, jan], _QUERY, LiteratureView.latest)

    assert _labels(result) == ["Later in 2024", "Earlier in 2024"]
    reason = result.items[1].rank_reasons[0]
    assert reason.label == (
        "Published 2024 — the source states a year only"
    )
    assert any("sorts at the start" in line for line in result.limitations)


def test_an_undated_record_is_listed_last_rather_than_given_a_date():
    undated = _item("No date at all", year=None, published_on=None)
    dated = _item("Dated", published_on="2015-01-01", published_precision="day")

    result = build_view([undated, dated], _QUERY, LiteratureView.latest)

    assert _labels(result) == ["Dated", "No date at all"]
    assert "No publication date reported" in result.items[-1].rank_reasons[0].label
    assert any("invented" in line for line in result.limitations)


def test_indexing_date_never_decides_the_latest_view():
    """A record indexed last year but published in 2009 is not a recent paper."""
    stale = _item(
        "Indexed recently",
        published_on="2009-05-05",
        published_precision="day",
        indexed_on="2026-02-01",
        indexed_field="entrez",
    )
    recent = _item("Published recently", published_on="2025-08-08", published_precision="day")

    result = build_view([stale, recent], _QUERY, LiteratureView.latest)

    assert _labels(result) == ["Published recently", "Indexed recently"]
    reasons = " | ".join(r.label for r in result.items[1].rank_reasons)
    assert "Indexed by PubMed on 2026-02-01" in reasons
    assert "not a publication date" in reasons


# --- Strongest evidence ----------------------------------------------------


def test_strongest_view_orders_by_the_design_the_source_reports():
    animal = _item(
        "Animal work", publication_types=["Animal"], evidence_type=EvidenceType.animal
    )
    rct = _item(
        "Randomised trial",
        publication_types=["Randomized Controlled Trial"],
        evidence_type=EvidenceType.randomized_controlled_trial,
    )
    editorial = _item(
        "An editorial", publication_types=["Editorial"], evidence_type=EvidenceType.editorial
    )

    result = build_view(
        [animal, editorial, rct], _QUERY, LiteratureView.strongest_evidence
    )

    assert _labels(result) == ["Randomised trial", "Animal work", "An editorial"]
    assert "Source reports this design: Randomized Controlled Trial" in (
        result.items[0].rank_reasons[0].label
    )


def test_strongest_view_computes_no_quality_score():
    """The ordering reads publication types; no number is attached to a paper."""
    items = [
        _item("A", publication_types=["Editorial"], evidence_type=EvidenceType.editorial),
        _item("B", publication_types=["Clinical Trial"], evidence_type=EvidenceType.clinical),
    ]

    result = build_view(items, _QUERY, LiteratureView.strongest_evidence)

    assert [item.relevance_score for item in result.items] == [0.0, 0.0]
    assert all(
        item.evidence_type.value in ("clinical", "editorial") for item in result.items
    )
    assert any(
        "not a score" in r.label for r in result.items[0].rank_reasons
    )


def test_a_correction_notice_is_listed_last_and_labelled_as_one():
    notice = _item(
        "Retraction notice",
        publication_types=["Retraction of Publication"],
        evidence_type=EvidenceType.correction_or_retraction,
    )
    cell = _item(
        "Cell work", publication_types=["In Vitro"], evidence_type=EvidenceType.cellular
    )

    result = build_view([cell, notice], _QUERY, LiteratureView.strongest_evidence)

    assert _labels(result) == ["Cell work", "Retraction notice"]
    assert result.items[-1].evidence_type == EvidenceType.correction_or_retraction
    assert any(
        "not as primary evidence" in r.label for r in result.items[-1].rank_reasons
    )


def test_records_with_no_reported_design_are_ordered_after_known_designs():
    unclassified = _item("No type reported")
    computational = _item(
        "Modelling", publication_types=["Simulation Study"],
        evidence_type=EvidenceType.computational,
    )

    result = build_view(
        [unclassified, computational], _QUERY, LiteratureView.strongest_evidence
    )

    assert _labels(result) == ["Modelling", "No type reported"]
    assert "no design position" in result.items[1].rank_reasons[0].label


# --- Reviews & guidelines --------------------------------------------------


def test_reviews_view_keeps_only_source_labelled_reviews():
    guideline = _item(
        "A guideline",
        published_on="2021-02-02",
        published_precision="day",
        publication_types=["Guideline", "Journal Article"],
        evidence_type=EvidenceType.literature_review,
    )
    meta = _item(
        "Meta-analysis",
        published_on="2023-03-03",
        published_precision="day",
        publication_types=["Meta-Analysis"],
        evidence_type=EvidenceType.systematic_review,
    )
    trial = _item(
        "A trial",
        published_on="2024-04-04",
        published_precision="day",
        publication_types=["Randomized Controlled Trial"],
        evidence_type=EvidenceType.randomized_controlled_trial,
    )

    result = build_view(
        [trial, meta, guideline], _QUERY, LiteratureView.reviews_guidelines
    )

    assert _labels(result) == ["Meta-analysis", "A guideline"]
    assert result.records_received == 3
    assert result.records_shown == 2
    assert any("name no review" in line for line in result.limitations)
    assert "Source labels this Meta-Analysis" == result.items[0].rank_reasons[0].label


def test_an_unlabelled_record_is_not_guessed_into_the_reviews_view():
    """Nothing in the reported types names a review, so the record is left out."""
    ambiguous = _item("Untyped", publication_types=["Journal Article"])

    result = build_view([ambiguous], _QUERY, LiteratureView.reviews_guidelines)

    assert result.items == []
    assert result.records_shown == 0


# --- Most relevant ---------------------------------------------------------


def test_most_relevant_quotes_the_words_it_matched_and_where():
    paper = _item(
        "TRPC5 in Alzheimer",
        abstract="Signalling through TRPC5 in Alzheimer disease.",
        publication_types=["Journal Article"],
    )
    unrelated = _item("A paper about soil")

    result = build_view([unrelated, paper], _QUERY, LiteratureView.most_relevant)

    assert _labels(result) == ["TRPC5 in Alzheimer", "A paper about soil"]
    labels = [r.label for r in result.items[0].rank_reasons]
    assert any(l.startswith("Title states") for l in labels)
    assert any(l.startswith("Abstract states") for l in labels)
    title_reason = next(r for r in result.items[0].rank_reasons if r.source_field == "title")
    assert "“trpc5”" in title_reason.label
    assert any(
        r.label.startswith("No query word appears")
        for r in result.items[1].rank_reasons
    )


def test_every_reason_names_a_field_the_record_carries():
    fields = set(EvidenceItem.model_fields)
    for view in LiteratureView:
        result = build_view(
            [_item("TRPC5 Alzheimer paper", published_on="2023-01-01",
                   publication_types=["Review"], indexed_on="2023-02-02")],
            _QUERY,
            view,
        )
        for item in result.items:
            for reason in item.rank_reasons:
                assert reason.source_field in fields, reason.source_field
            assert item.view == view


# --- Filters ---------------------------------------------------------------


def test_open_access_filter_reports_that_unstated_is_not_the_same_as_closed():
    stated = _item("Open", pmid="1", source="EuropePMC", open_access=True)
    closed = _item("Closed", pmid="2", source="EuropePMC", open_access=False)
    unknown = _item("Unstated", pmid="3", source="PubMed")

    result = build_view(
        [stated, closed, unknown],
        _QUERY,
        LiteratureView.latest,
        LiteratureFilters(open_access=True),
    )

    assert _labels(result) == ["Open"]
    exclusion = next(e for e in result.exclusions if e.filter == "open_access")
    assert exclusion.removed == 2
    assert "'not stated' is not 'not open access'" in exclusion.note


def test_publication_type_filter_can_select_a_retraction_notice():
    notice = _item(
        "Retraction of a study",
        pmid="4",
        publication_types=["Retraction of Publication"],
        evidence_type=EvidenceType.correction_or_retraction,
        published_on="2022-01-01",
        published_precision="day",
    )
    research = _item(
        "Original study",
        pmid="5",
        publication_types=["Journal Article"],
        published_on="2021-01-01",
        published_precision="day",
    )

    result = build_view(
        [notice, research],
        _QUERY,
        LiteratureView.latest,
        LiteratureFilters(publication_types=["Retraction"]),
    )

    assert _labels(result) == ["Retraction of a study"]
    assert result.items[0].evidence_type == EvidenceType.correction_or_retraction


def test_clinical_scope_excludes_preclinical_and_unclassified_records():
    rct = _item("Trial", pmid="6", publication_types=["Randomized Controlled Trial"],
                evidence_type=EvidenceType.randomized_controlled_trial)
    animal = _item("Mouse study", pmid="7", publication_types=["Animal"],
                   evidence_type=EvidenceType.animal)
    untyped = _item("No type", pmid="8")

    result = build_view(
        [rct, animal, untyped],
        _QUERY,
        LiteratureView.latest,
        LiteratureFilters(study_scope="clinical"),
    )

    assert _labels(result) == ["Trial"]
    exclusion = next(e for e in result.exclusions if e.filter == "study_scope")
    assert exclusion.removed == 2
    assert "in neither scope" in exclusion.note


def test_date_range_filter_drops_records_stating_no_date_and_says_so():
    inside = _item("Inside", pmid="9", published_on="2021-05-05", published_precision="day")
    outside = _item("Outside", pmid="10", published_on="2019-01-01", published_precision="day")
    blank = _item("Blank", pmid="11", year=None)

    result = build_view(
        [inside, outside, blank],
        _QUERY,
        LiteratureView.latest,
        LiteratureFilters(published_from="2020", published_to="2022"),
    )

    assert _labels(result) == ["Inside"]
    exclusion = next(e for e in result.exclusions if e.filter == "published_on")
    assert exclusion.removed == 2
    assert "not the same as having no" in exclusion.note


def test_source_filter_keeps_the_named_database():
    epmc = _item("From EPMC", pmid="12", source="EuropePMC", published_on="2020")
    pubmed = _item("From PubMed", pmid="13", published_on="2020")

    result = build_view(
        [epmc, pubmed],
        _QUERY,
        LiteratureView.latest,
        LiteratureFilters(sources=["EuropePMC"]),
    )

    assert _labels(result) == ["From EPMC"]


def test_subtype_filter_uses_the_disease_wording_rule():
    """A paper naming the subtype in its own title counts; one naming the
    opposite wording does not."""
    nsclc = _item(
        "Treatment of non-small cell lung carcinoma",
        pmid="14",
        published_on="2023-01-01",
        published_precision="day",
    )
    small = _item(
        "Treatment of small cell lung carcinoma",
        pmid="15",
        published_on="2022-01-01",
        published_precision="day",
    )

    result = build_view(
        [nsclc, small],
        "lung carcinoma",
        LiteratureView.latest,
        LiteratureFilters(subtype_label="non-small cell lung carcinoma"),
    )

    assert _labels(result) == ["Treatment of non-small cell lung carcinoma"]
    exclusion = next(e for e in result.exclusions if e.filter == "subtype")
    assert exclusion.removed == 1


def test_target_filter_reads_the_target_names_retrieved_for_this_query():
    naming = _item(
        "Signalling through TRPC5 in disease",
        pmid="16",
        published_on="2023",
        published_precision="year",
    )
    other = _item(
        "An unrelated enzyme",
        pmid="17",
        published_on="2023",
        published_precision="year",
    )

    result = build_view(
        [naming, other],
        _QUERY,
        LiteratureView.latest,
        LiteratureFilters(target_terms=["TRPC5"], relevance_to_target=True),
    )

    assert _labels(result) == ["Signalling through TRPC5 in disease"]
    exclusion = next(e for e in result.exclusions if e.filter == "target")
    assert "not evidence that the study acted on that target" in exclusion.note


def test_regulatory_records_are_not_listed_as_literature():
    paper = _item("A paper", pmid="18", published_on="2023")
    label = _item(
        "Label text", source="openFDA", source_type="regulatory", published_on="2023"
    )

    result = build_view([paper, label], _QUERY, LiteratureView.latest)

    assert _labels(result) == ["A paper"]
    assert result.exclusions[0].filter == "source_type"


# --- Facets and merged provenance -----------------------------------------


def test_facets_are_counted_before_filtering_so_the_options_stay_visible():
    items = [
        _item("Open A", pmid="19", source="EuropePMC", open_access=True,
              publication_types=["Review"], published_on="2020"),
        _item("Closed B", pmid="20", source="PubMed", open_access=False,
              publication_types=["Editorial"], published_on="2021"),
    ]

    result = build_view(
        items, _QUERY, LiteratureView.latest, LiteratureFilters(sources=["PubMed"])
    )

    facet_counts = {(f.field, f.value): f.count for f in result.facets}
    assert facet_counts[("source", "EuropePMC")] == 1
    assert facet_counts[("publication_type", "Review")] == 1
    assert result.records_received == 2
    assert result.records_shown == 1


def test_a_merged_publication_reports_the_records_behind_it():
    merged = _item("One paper two records", pmid="21", published_on="2022")
    merged.merged_records = 2
    merged.merged_sources = ["PubMed", "EuropePMC"]
    merged.links = ["https://pubmed.ncbi.nlm.nih.gov/21/", "https://doi.org/10.1/x"]

    result = build_view([merged], _QUERY, LiteratureView.latest)

    reason = result.items[0].rank_reasons
    assert any(
        "assembled from 2 retrieved record(s)" in r.label for r in reason
    )
    assert any(r.source_field == "merged_records" for r in reason)


def test_the_view_rule_is_shown_with_the_ordered_list():
    result = build_view([_item("Any", published_on="2020")], _QUERY, LiteratureView.latest)

    assert result.view == LiteratureView.latest
    assert "publication date" in result.rule
    assert result.dates_note == (
        "Dates are the publication dates the sources state, at the precision they "
        "state them. A database's indexing date is reported separately and is "
        "never used as a publication date."
    )


# --- Endpoints -------------------------------------------------------------


def test_merge_counts_cover_publications_not_regulatory_passages():
    """The dossier's counts describe the literature, though the evidence list is mixed.

    An openFDA passage is a label excerpt, not a publication, so counting it as
    a record that was merged into a publication would overstate the retrieval.
    """
    from services.evidence_normalizer import deduplicate

    same_paper = [
        _item("Shared paper", pmid="80", published_on="2022", published_precision="year"),
        _item(
            "Shared paper",
            source="EuropePMC",
            pmid="80",
            published_on="2022-03-04",
            published_precision="day",
        ),
    ]
    label = _item(
        "Indications and usage",
        source="openFDA",
        source_type="regulatory",
        published_on="2022",
        published_precision="year",
    )

    result = build_view(deduplicate(same_paper + [label]), _QUERY)

    report = result.deduplication
    assert report.records_received == 2
    assert report.publications == 1
    assert report.records_merged == 1
    assert report.cross_database_merges == 1
    assert report.records_without_identifier == 0


def test_views_endpoint_reranks_without_calling_a_source():
    """The dossier posts the records it already holds; no source is queried twice."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from api import literature

    app = FastAPI()
    app.include_router(literature.router, prefix="/api")
    client = TestClient(app)

    older = _item("Older", pmid="30", published_on="2019", published_precision="year")
    newer = _item(
        "Newer", pmid="31", published_on="2021-01-01", published_precision="day"
    )
    # The dossier's records are already merged, and carry how that was done.
    newer.merged_records = 2
    newer.merged_sources = ["PubMed", "EuropePMC"]

    body = {
        "query": _QUERY,
        "view": "latest",
        "items": [older.model_dump(), newer.model_dump()],
    }
    response = client.post("/api/literature/views", json=body)

    assert response.status_code == 200
    payload = response.json()
    assert [item["title"] for item in payload["items"]] == ["Newer", "Older"]
    assert payload["label"] == "Latest"
    report = payload["deduplication"]
    assert report["records_received"] == 3
    assert report["publications"] == 2
    assert report["records_merged"] == 1
    assert report["cross_database_merges"] == 1


def test_literature_endpoint_merges_the_two_databases_before_ordering(monkeypatch):
    """GET /api/literature reports the merge it did alongside the ordered list."""
    import asyncio

    from api import literature

    async def fake_pubmed(query, max_results=25):
        return [_item("Shared paper", pmid="40", doi="10.1/shared",
                      published_on="2022", published_precision="year")]

    async def fake_epmc(query, max_results=25):
        return [
            _item("Shared paper", pmid="40", source="EuropePMC", open_access=True,
                  published_on="2022-05-05", published_precision="day"),
            _item("EPMC only", pmid="41", source="EuropePMC",
                  published_on="2021", published_precision="year"),
        ]

    monkeypatch.setattr(literature.pubmed, "search_literature", fake_pubmed)
    monkeypatch.setattr(literature.europepmc, "search_literature", fake_epmc)

    result = asyncio.run(literature.search_literature("TRPC5", view=LiteratureView.latest))

    assert [item.title for item in result.items] == ["Shared paper", "EPMC only"]
    report = result.deduplication
    assert report.records_received == 3
    assert report.publications == 2
    assert report.cross_database_merges == 1
    # The merged copy carries the day Europe PMC stated, and its open-access flag
    merged = result.items[0]
    assert merged.published_on == "2022-05-05"
    assert merged.open_access is True
    assert merged.merged_records == 2
