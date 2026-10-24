"""Unit tests for evidence normalization and deduplication."""

from __future__ import annotations

from models.schemas import EvidenceItem, EvidenceType
from services.evidence_normalizer import (
    deduplicate,
    deduplicate_with_report,
    normalize_evidence_list,
    report_from_provenance,
)


def _make_item(
    source: str = "PubMed",
    pmid: str | None = None,
    doi: str | None = None,
    abstract: str | None = None,
    authors: list[str] | None = None,
) -> EvidenceItem:
    """Create a minimal EvidenceItem for testing."""
    return EvidenceItem(
        source=source,
        source_type="literature",
        id=pmid,
        title="Test Title",
        year=2023,
        authors=authors or [],
        abstract=abstract,
        evidence_type=EvidenceType.literature_review,
        metadata={"pmid": pmid, "doi": doi},
    )


def test_deduplication_by_pmid():
    """Two items with the same PMID from different sources — only one kept."""
    item_pm = _make_item(source="PubMed", pmid="11111111")
    item_epmc = _make_item(source="EuropePMC", pmid="11111111")

    result = deduplicate([item_pm, item_epmc])

    assert len(result) == 1


def test_deduplication_by_doi():
    """Two items with the same DOI from different sources — only one kept."""
    item1 = _make_item(source="PubMed", doi="10.1234/test.001")
    item2 = _make_item(source="EuropePMC", doi="10.1234/test.001")

    result = deduplicate([item1, item2])

    assert len(result) == 1


def test_normalize_truncates_long_abstract():
    """An item with a 2000-character abstract is truncated."""
    long_abstract = "A" * 2000
    item = _make_item(abstract=long_abstract)

    normalized = normalize_evidence_list([item])

    assert len(normalized) == 1
    # Should be truncated (800 chars + ellipsis)
    assert len(normalized[0].abstract) <= 810


def test_dedup_prefers_pubmed():
    """When PubMed and EuropePMC share a PMID, PubMed item is kept."""
    item_pm = _make_item(
        source="PubMed", pmid="22222222", abstract="PubMed abstract"
    )
    item_epmc = _make_item(
        source="EuropePMC", pmid="22222222", abstract="EPMC abstract"
    )

    result = deduplicate([item_epmc, item_pm])  # EuropePMC first

    assert len(result) == 1
    assert result[0].source == "PubMed"


# --- spec §7.1: identifier keys, retained provenance, no title merging ------


def _lit(
    source: str,
    pmid: str | None = None,
    pmcid: str | None = None,
    doi: str | None = None,
    **kwargs,
) -> EvidenceItem:
    """A literature record carrying the identifiers Europe PMC or PubMed state."""
    return EvidenceItem(
        source=source,
        source_type="literature",
        id=pmid or pmcid or doi,
        title=kwargs.pop("title", "Test Title"),
        pmid=pmid,
        pmcid=pmcid,
        doi=doi,
        links=kwargs.pop("links", []),
        **kwargs,
    )


def test_pmcid_alone_merges_two_records_of_the_same_paper():
    """Europe PMC keys on PMCID for a paper PubMed lists without a PMID.

    Before PMCID was a key the two copies of the paper were listed twice, and a
    reader counted two publications where the sources hold one.
    """
    epmc = _lit("EuropePMC", pmcid="PMC1122334", title="Same paper")
    pubmed = _lit("PubMed", pmcid="1122334", title="Same paper")

    merged, report = deduplicate_with_report([epmc, pubmed])

    assert len(merged) == 1
    # "1122334" and "PMC1122334" are the same id written two ways
    assert merged[0].pmcid == "PMC1122334"
    assert report.publications == 1
    assert report.records_merged == 1


def test_merged_record_keeps_every_source_link():
    """Deduplicating must not discard a record's own link."""
    pubmed = _lit(
        "PubMed", pmid="33445566", links=["https://pubmed.ncbi.nlm.nih.gov/33445566/"]
    )
    epmc = _lit(
        "EuropePMC",
        pmid="33445566",
        doi="10.1000/x",
        links=["https://europepmc.org/article/MED/33445566"],
    )

    merged, report = deduplicate_with_report([pubmed, epmc])

    assert len(merged) == 1
    item = merged[0]
    assert "https://pubmed.ncbi.nlm.nih.gov/33445566/" in item.links
    assert "https://europepmc.org/article/MED/33445566" in item.links
    # The DOI only Europe PMC stated is now on the merged record
    assert item.doi == "10.1000/x"
    assert item.merged_records == 2
    assert set(item.merged_sources) == {"PubMed", "EuropePMC"}
    assert report.cross_database_merges == 1


def test_a_shared_doi_and_pmid_join_two_matches_into_one_publication():
    """One record naming both ids bridges the groups the other records form."""
    first = _lit("PubMed", pmid="111", doi="10.1000/bridge")
    second = _lit("EuropePMC", doi="10.1000/bridge")
    third = _lit("EuropePMC", pmid="111")

    merged, report = deduplicate_with_report([first, second, third])

    assert len(merged) == 1
    assert merged[0].merged_records == 3
    assert report.records_merged == 2
    assert report.merged_publications == 1


def test_identical_titles_without_a_shared_identifier_are_not_merged():
    """Two different papers can be named alike; only an identifier proves a match."""
    first = _lit("PubMed", pmid="20000001", title="Role of TRPC5 in Disease")
    second = _lit("EuropePMC", pmid="29999999", title="Role of TRPC5 in Disease")

    merged, report = deduplicate_with_report([first, second])

    assert len(merged) == 2
    assert report.publications == 2
    assert report.records_merged == 0
    assert report.never_matched_on == ["title similarity", "author similarity"]


def test_records_without_any_identifier_are_counted_not_dropped():
    """A record with no PMID, PMCID or DOI is listed alone and reported."""
    anonymous = EvidenceItem(
        source="EuropePMC", source_type="literature", title="No identifiers here"
    )

    merged, report = deduplicate_with_report([anonymous])

    assert len(merged) == 1
    assert report.records_without_identifier == 1
    assert report.publications == 1


def test_merge_takes_the_more_precise_publication_date_from_either_record():
    """Europe PMC states a day where PubMed states a year; the paper has one date."""
    coarse = _lit("PubMed", pmid="40000001", published_on="2024", published_precision="year")
    exact = _lit(
        "EuropePMC",
        pmid="40000001",
        published_on="2024-03-07",
        published_precision="day",
        abstract="Longer abstract here.",
    )

    merged, _ = deduplicate_with_report([coarse, exact])

    assert merged[0].published_on == "2024-03-07"
    assert merged[0].published_precision == "day"
    # The base record is PubMed's, so the flag only Europe PMC states is carried over
    assert merged[0].source == "PubMed"


def test_open_access_is_carried_from_whichever_record_states_it():
    closed = _lit("PubMed", pmid="50000001")
    open_copy = _lit("EuropePMC", pmid="50000001", open_access=True)

    merged, _ = deduplicate_with_report([closed, open_copy])

    assert merged[0].open_access is True


def test_an_absent_open_access_flag_is_not_read_as_closed_access():
    """Neither record states open access, so the merged record knows nothing."""
    a = _lit("PubMed", pmid="60000001")
    b = _lit("PubMed", pmid="60000001", abstract="Second copy")

    merged, _ = deduplicate_with_report([a, b])

    assert merged[0].open_access is None


def test_provenance_reproduces_the_retrieval_merge_counts():
    """A view re-ordered later can state the same counts without the old report.

    The dossier POSTs records that were already merged, so the view endpoint
    rebuilds the merge counts from the provenance each publication carries.
    """
    items = [
        _lit("PubMed", pmid="70000001", doi="10.1/a"),
        _lit("EuropePMC", pmid="70000001", title="Copy in Europe PMC"),
        _lit("EuropePMC", pmcid="PMC70000002", title="Only in Europe PMC"),
        _lit("PubMed", title="No identifiers to merge on"),
    ]

    merged, retrieval = deduplicate_with_report(items)
    again = report_from_provenance(merged)

    assert again.records_received == retrieval.records_received == 4
    assert again.publications == retrieval.publications == len(merged)
    assert again.records_merged == retrieval.records_merged == 1
    assert again.merged_publications == retrieval.merged_publications == 1
    assert again.cross_database_merges == retrieval.cross_database_merges == 1
    assert again.records_without_identifier == retrieval.records_without_identifier == 1
