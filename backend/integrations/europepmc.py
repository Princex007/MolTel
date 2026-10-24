"""Europe PMC REST API integration."""

from __future__ import annotations

import logging
from typing import Optional

from models.schemas import EvidenceItem, EvidenceType
from utils.dates import normalize_date
from utils.evidence_types import classify_publication_types
from utils.http import safe_get
from utils.text import normalize_doi

logger = logging.getLogger(__name__)

BASE_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest"


async def search_literature(query: str, max_results: int = 25) -> list[EvidenceItem]:
    """Search Europe PMC and return a list of EvidenceItems."""
    url = f"{BASE_URL}/search"
    params = {
        "query": query,
        "format": "json",
        "pageSize": str(max_results),
        "resultType": "core",
    }
    data = await safe_get(url, params=params)
    if data is None:
        return []

    results = data.get("resultList", {}).get("result", [])
    items: list[EvidenceItem] = []
    for result in results:
        item = _parse_result(result)
        if item:
            items.append(item)
    return items


def _parse_result(result: dict) -> Optional[EvidenceItem]:
    """Parse a single Europe PMC result dict into an EvidenceItem."""
    pmid: Optional[str] = result.get("pmid")
    pmcid: Optional[str] = result.get("pmcid")
    doi_raw: Optional[str] = result.get("doi")
    doi = normalize_doi(doi_raw)

    title: Optional[str] = result.get("title")
    author_string: Optional[str] = result.get("authorString")
    authors: list[str] = []
    if author_string:
        # authorString is comma-separated, e.g. "Smith J, Jones A."
        authors = [a.strip().rstrip(".") for a in author_string.split(",") if a.strip()]

    year_str: Optional[str] = result.get("pubYear")
    year: Optional[int] = None
    if year_str:
        try:
            year = int(year_str)
        except ValueError:
            pass

    abstract: Optional[str] = result.get("abstractText")

    # Journal title: top-level on 'lite', nested under journalInfo on 'core'
    journal: Optional[str] = result.get("journalTitle")
    if not journal:
        journal = result.get("journalInfo", {}).get("journal", {}).get("title")

    pub_types: list[str] = result.get("pubTypeList", {}).get("pubType", [])
    if not pub_types and result.get("pubType"):
        pub_types = [result["pubType"]]
    pub_types = [p.strip() for p in pub_types if p and p.strip()]
    evidence_type = classify_publication_types(pub_types) or EvidenceType.other

    # Publication date: the print date the source states, falling back to the
    # electronic date, then to the year. Nothing is padded to look precise.
    published_on, published_precision = normalize_date(
        result.get("firstPublicationDate")
    )
    if published_on is None:
        published_on, published_precision = normalize_date(
            result.get("electronicPublicationDate")
        )
    if published_on is None and year is not None:
        published_on, published_precision = normalize_date(str(year))

    # Indexing dates the source publishes, kept apart from publication date
    indexed_on, _ = normalize_date(result.get("firstIndexDate"))
    indexed_field: Optional[str] = "firstIndexDate" if indexed_on else None
    if indexed_on is None:
        indexed_on, _ = normalize_date(result.get("dateOfCreation"))
        indexed_field = "dateOfCreation" if indexed_on else None

    # isOpenAccess is a Y/N flag on the record, not an inference
    open_access_raw = result.get("isOpenAccess")
    open_access: Optional[bool] = None
    if open_access_raw == "Y":
        open_access = True
    elif open_access_raw == "N":
        open_access = False

    links: list[str] = []
    if pmid:
        links.append(f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/")
    if pmcid:
        links.append(f"https://www.ncbi.nlm.nih.gov/pmc/articles/{pmcid}/")
    if doi:
        links.append(f"https://doi.org/{doi}")
    # europepmc.org is this source's own record of the article, so it is kept as
    # a link even when a publisher DOI exists
    if pmid:
        url = f"https://europepmc.org/article/MED/{pmid}"
    elif pmcid:
        url = f"https://europepmc.org/article/PMC/{pmcid}"
    elif doi:
        url = f"https://doi.org/{doi}"
    else:
        url = None
    if url:
        links.append(url)

    item_id = pmid or pmcid or doi

    return EvidenceItem(
        source="EuropePMC",
        source_type="literature",
        id=item_id,
        title=title,
        year=year,
        authors=authors,
        abstract=abstract,
        url=url,
        evidence_type=evidence_type,
        pmid=pmid,
        pmcid=pmcid,
        doi=doi,
        published_on=published_on,
        published_precision=published_precision,
        indexed_on=indexed_on,
        indexed_field=indexed_field,
        publication_types=pub_types,
        open_access=open_access,
        journal=journal,
        links=links,
        merged_sources=["EuropePMC"],
        metadata={
            "pmid": pmid,
            "pmcid": pmcid,
            "doi": doi,
            "journal": journal,
            "publication_types": pub_types,
        },
    )
