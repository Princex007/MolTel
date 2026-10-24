"""Evidence normalization and deduplication service."""

from __future__ import annotations

from models.schemas import EvidenceDeduplication, EvidenceItem
from utils.text import (
    clean_whitespace,
    normalize_doi,
    normalize_pmcid,
    truncate,
)

_MAX_ABSTRACT_CHARS = 800
_MAX_TITLE_CHARS = 300

# How exactly a source states a publication date. A day is not better science
# than a year; it only sorts more exactly against other dates.
PRECISION_RANK = {"day": 3, "month": 2, "year": 1}


def normalize_evidence_list(items: list[EvidenceItem]) -> list[EvidenceItem]:
    """Normalize a list of EvidenceItems in-place and return the list."""
    normalized: list[EvidenceItem] = []
    for item in items:
        item = item.model_copy()
        if item.title:
            item.title = truncate(clean_whitespace(item.title), _MAX_TITLE_CHARS)
        if item.abstract:
            item.abstract = truncate(clean_whitespace(item.abstract), _MAX_ABSTRACT_CHARS)
        if item.source:
            item.source = item.source.strip()
        if item.id:
            item.id = item.id.strip()
        normalized.append(item)
    return normalized


def deduplicate(items: list[EvidenceItem]) -> list[EvidenceItem]:
    """Merge the records that name the same publication, keeping all provenance."""
    merged, _ = deduplicate_with_report(items)
    return merged


def deduplicate_with_report(
    items: list[EvidenceItem],
) -> tuple[list[EvidenceItem], EvidenceDeduplication]:
    """Group retrieved records by PMID, PMCID or DOI and report how that went.

    A record is the same publication as another only when one of those three
    identifiers matches. Title wording is never compared: two different papers
    can carry near-identical titles, and merging them would attach one paper's
    links to another. A record stating several identifiers joins every group
    those identifiers appear in, so one publication is never listed twice.
    """
    parent = list(range(len(items)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(a: int, b: int) -> None:
        root_a, root_b = find(a), find(b)
        if root_a != root_b:
            parent[max(root_a, root_b)] = min(root_a, root_b)

    key_owner: dict[tuple[str, str], int] = {}
    for index, item in enumerate(items):
        for key in _identity_keys(item):
            owner = key_owner.get(key)
            if owner is None:
                key_owner[key] = index
            else:
                union(owner, index)

    groups: dict[int, list[EvidenceItem]] = {}
    for index, item in enumerate(items):
        groups.setdefault(find(index), []).append(item)

    merged = [_normalize_identifiers(_merge_group(group)) for group in groups.values()]
    multi = [group for group in groups.values() if len(group) > 1]
    report = EvidenceDeduplication(
        records_received=len(items),
        publications=len(merged),
        records_merged=len(items) - len(merged),
        merged_publications=len(multi),
        cross_database_merges=sum(
            1 for group in multi if len({item.source for item in group}) > 1
        ),
        records_without_identifier=sum(
            1 for item in items if not _identity_keys(item)
        ),
    )
    return merged, report


def report_from_provenance(items: list[EvidenceItem]) -> EvidenceDeduplication:
    """Recover the merge counts from publications that were already merged.

    Each merged publication carries how many retrieved records were folded into
    it and which sources those came from, so re-ordering a list later can still
    state the counts without the caller passing the original report back.
    """
    received = sum(max(1, item.merged_records or 1) for item in items)
    merged = [item for item in items if (item.merged_records or 1) > 1]
    return EvidenceDeduplication(
        records_received=received,
        publications=len(items),
        records_merged=received - len(items),
        merged_publications=len(merged),
        cross_database_merges=sum(
            1 for item in merged if len(set(item.merged_sources or [])) > 1
        ),
        records_without_identifier=sum(1 for item in items if not _identity_keys(item)),
    )


def _identity_keys(item: EvidenceItem) -> list[tuple[str, str]]:
    keys: list[tuple[str, str]] = []
    for kind, getter in (
        ("pmid", _get_pmid),
        ("pmcid", _get_pmcid),
        ("doi", _get_doi),
    ):
        value = getter(item)
        if value:
            keys.append((kind, value))
    return keys


def _merge_group(group: list[EvidenceItem]) -> EvidenceItem:
    """Build one publication record out of every retrieved record naming it.

    The most complete record is the base and nothing it lacks is invented: each
    field is filled from a record that actually states it. Links, identifiers
    and publication types are unioned, so no source's link is dropped.
    """
    if len(group) == 1:
        item = group[0].model_copy()
        if not item.merged_sources:
            item.merged_sources = [item.source]
        item.merged_records = 1
        return item

    base = group[0]
    for candidate in group[1:]:
        base = _prefer(base, candidate)
    item = base.model_copy()

    sources: list[str] = []
    links: list[str] = []
    pub_types: list[str] = []
    authors: list[str] = []
    for other in group:
        for name in [other.source, *other.merged_sources]:
            if name and name not in sources:
                sources.append(name)
        for link in [other.url, *other.links]:
            if link and link not in links:
                links.append(link)
        for ptype in other.publication_types:
            if ptype and ptype not in pub_types:
                pub_types.append(ptype)
        for author in other.authors:
            if author and author not in authors:
                authors.append(author)
        item.pmid = item.pmid or _get_pmid(other)
        item.pmcid = item.pmcid or _get_pmcid(other)
        item.doi = item.doi or _get_doi(other)
        if not item.indexed_on and other.indexed_on:
            item.indexed_on = other.indexed_on
            item.indexed_field = other.indexed_field
        if other.open_access is True:
            item.open_access = True
        elif other.open_access is False and item.open_access is None:
            item.open_access = False
        if _more_precise(other, item):
            item.published_on = other.published_on
            item.published_precision = other.published_precision

    item.merged_sources = sources
    item.merged_records = sum(other.merged_records for other in group)
    item.links = links
    item.publication_types = pub_types
    if authors:
        item.authors = authors
    if not item.url:
        item.url = links[0] if links else None
    for field in ("title", "abstract", "journal"):
        if not getattr(item, field):
            setattr(
                item,
                field,
                next((getattr(o, field) for o in group if getattr(o, field)), None),
            )
    if item.year is None:
        item.year = next((o.year for o in group if o.year is not None), None)
    return item


def _normalize_identifiers(item: EvidenceItem) -> EvidenceItem:
    """Write each identifier in one form, whichever shape the source used.

    PubMed lists a PMC id as "1234567" and Europe PMC as "PMC1234567". Neither is
    a different paper, and a reader comparing two lists should see one form. The
    URL prefix on a DOI is dropped for the same reason.
    """
    item.pmid = _get_pmid(item)
    item.pmcid = _get_pmcid(item)
    item.doi = _get_doi(item)
    return item


def _more_precise(other: EvidenceItem, item: EvidenceItem) -> bool:
    """Whether `other` states the publication date more exactly than `item`."""
    if not other.published_on:
        return False
    if not item.published_on:
        return True
    return PRECISION_RANK.get(other.published_precision or "year", 0) > (
        PRECISION_RANK.get(item.published_precision or "year", 0)
    )


def _get_pmid(item: EvidenceItem) -> str | None:
    """Extract a bare PMID from an EvidenceItem."""
    for raw in (item.pmid, item.metadata.get("pmid")):
        if raw:
            text = str(raw).strip()
            if text:
                return text
    # PubMed items store PMID as their id
    if item.source == "PubMed" and item.id:
        return item.id.strip()
    return None


def _get_pmcid(item: EvidenceItem) -> str | None:
    """Extract a PMCID, prefixed the same way whichever source stated it."""
    return normalize_pmcid(item.pmcid or item.metadata.get("pmcid"))


def _get_doi(item: EvidenceItem) -> str | None:
    """Extract normalized DOI from an EvidenceItem."""
    doi = normalize_doi(item.doi or item.metadata.get("doi"))
    if doi:
        return doi.lower()
    return None


def _prefer(a: EvidenceItem, b: EvidenceItem) -> EvidenceItem:
    """Return the more complete / preferred of two duplicate EvidenceItems."""
    # Prefer PubMed over EuropePMC
    if a.source == "PubMed" and b.source != "PubMed":
        return a
    if b.source == "PubMed" and a.source != "PubMed":
        return b
    # Otherwise prefer the one with more data (abstract + authors)
    score_a = (1 if a.abstract else 0) + len(a.authors)
    score_b = (1 if b.abstract else 0) + len(b.authors)
    return a if score_a >= score_b else b
