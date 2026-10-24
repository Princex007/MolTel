"""NCBI E-utilities (PubMed) integration."""

from __future__ import annotations

import logging
import os
import xml.etree.ElementTree as ET
from typing import Optional

from models.schemas import EvidenceItem, EvidenceType
from utils.dates import precision_from_parts
from utils.evidence_types import classify_publication_types
from utils.http import get_async_client
from utils.text import normalize_doi

logger = logging.getLogger(__name__)

BASE_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"


async def search_literature(query: str, max_results: int = 25) -> list[EvidenceItem]:
    """Search PubMed and return a list of EvidenceItems."""
    email = os.getenv("NCBI_EMAIL", "researcher@example.com")

    # Step 1: esearch to get PMIDs
    pmids = await _esearch(query, max_results, email)
    if not pmids:
        return []

    # Step 2: efetch to get article details
    return await _efetch(pmids, email)


async def _esearch(query: str, max_results: int, email: str) -> list[str]:
    """Run esearch and return a list of PMIDs."""
    url = f"{BASE_URL}/esearch.fcgi"
    params = {
        "db": "pubmed",
        "term": query,
        "retmax": str(max_results),
        "retmode": "json",
        "tool": "MolTel",
        "email": email,
    }
    try:
        async with get_async_client() as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            data = response.json()
    except Exception as exc:  # noqa: BLE001
        logger.warning("PubMed esearch failed for '%s': %s", query, exc)
        return []

    id_list = data.get("esearchresult", {}).get("idlist", [])
    return id_list


async def _efetch(pmids: list[str], email: str) -> list[EvidenceItem]:
    """Fetch article details by PMIDs from PubMed."""
    url = f"{BASE_URL}/efetch.fcgi"
    params = {
        "db": "pubmed",
        "id": ",".join(pmids),
        "retmode": "xml",
        "rettype": "abstract",
        "tool": "MolTel",
        "email": email,
    }
    try:
        async with get_async_client() as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            xml_text = response.text
    except Exception as exc:  # noqa: BLE001
        logger.warning("PubMed efetch failed: %s", exc)
        return []

    return _parse_pubmed_xml(xml_text)


def _parse_pubmed_xml(xml_text: str) -> list[EvidenceItem]:
    """Parse PubMed XML into a list of EvidenceItems."""
    items: list[EvidenceItem] = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        logger.warning("PubMed XML parse error: %s", exc)
        return []

    for article in root.findall(".//PubmedArticle"):
        try:
            item = _parse_article(article)
            if item:
                items.append(item)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Error parsing PubMed article: %s", exc)

    return items


def _parse_article(article: ET.Element) -> Optional[EvidenceItem]:
    """Parse a single PubmedArticle XML element."""
    medline = article.find("MedlineCitation")
    if medline is None:
        return None

    # PMID
    pmid_el = medline.find("PMID")
    pmid = pmid_el.text if pmid_el is not None else None

    art = medline.find("Article")
    if art is None:
        return None

    # Title
    title_el = art.find("ArticleTitle")
    title = "".join(title_el.itertext()) if title_el is not None else None

    # Authors
    authors: list[str] = []
    author_list = art.find("AuthorList")
    if author_list is not None:
        for author in author_list.findall("Author"):
            last = author.findtext("LastName", "")
            fore = author.findtext("ForeName", "")
            name = f"{last} {fore}".strip()
            if name:
                authors.append(name)

    # Abstract — structured abstracts carry multiple AbstractText elements
    abstract_els = art.findall("Abstract/AbstractText")
    abstract: Optional[str] = None
    if abstract_els:
        parts = []
        for el in abstract_els:
            label = el.get("Label")
            body = "".join(el.itertext()).strip()
            if not body:
                continue
            parts.append(f"{label}: {body}" if label else body)
        abstract = " ".join(parts) if parts else None

    # Publication date. ArticleDate is the electronic/publication date the
    # publisher states and carries year/month/day; PubDate is the journal's
    # printed date and is often only a year or a free-text MedlineDate.
    year: Optional[int] = None
    published_on, published_precision = _article_date(art)
    if published_on is not None:
        year = int(published_on[:4])
    else:
        pub_date = art.find(".//PubDate")
        year_el = pub_date.find("Year") if pub_date is not None else None
        if year_el is not None and year_el.text:
            try:
                year = int(year_el.text)
            except ValueError:
                pass
        if year is None:
            medline_date = pub_date.find("MedlineDate") if pub_date is not None else None
            if medline_date is not None and medline_date.text:
                import re

                m = re.search(r"\b(\d{4})\b", medline_date.text)
                if m:
                    year = int(m.group(1))
        if published_on is None and year is not None:
            # The journal stated a year and no month or day. That is recorded as
            # a year, not padded into a date.
            published_on, published_precision = f"{year}", "year"

    # Identifiers: PMID, PMC ID and DOI all key the same paper
    doi: Optional[str] = None
    pmcid: Optional[str] = None
    pub_data = article.find("PubmedData")
    if pub_data is not None:
        for aid in pub_data.findall(".//ArticleId"):
            id_type = aid.get("IdType")
            if id_type == "doi" and doi is None:
                doi = aid.text
            elif id_type == "pmc" and pmcid is None:
                pmcid = aid.text

    # Date the database indexed the record — not a publication date
    indexed_on, indexed_field = _entrez_history(pub_data)

    # Publication types drive the evidence classification
    pub_types = [
        (el.text or "").strip()
        for el in art.findall("PublicationTypeList/PublicationType")
    ]
    pub_types = [p for p in pub_types if p]
    evidence_type = classify_publication_types(pub_types) or EvidenceType.other

    journal_title = article.findtext(".//ISOAbbreviation") or medline.findtext(
        "MedlineJournalInfo/Medium"
    )

    links = [f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"] if pmid else []
    url = links[0] if links else None
    if pmcid:
        links.append(f"https://www.ncbi.nlm.nih.gov/pmc/articles/{pmcid}/")
    if doi:
        links.append(f"https://doi.org/{normalize_doi(doi)}")

    return EvidenceItem(
        source="PubMed",
        source_type="literature",
        id=pmid,
        title=title,
        year=year,
        authors=authors,
        abstract=abstract,
        url=url,
        evidence_type=evidence_type,
        pmid=pmid,
        pmcid=pmcid,
        doi=normalize_doi(doi) if doi else None,
        published_on=published_on,
        published_precision=published_precision,
        indexed_on=indexed_on,
        indexed_field=indexed_field,
        publication_types=pub_types,
        journal=journal_title,
        links=links,
        merged_sources=["PubMed"],
        metadata={
            "doi": doi,
            "pmid": pmid,
            "pmcid": pmcid,
            "publication_types": pub_types,
            "journal": journal_title,
        },
    )


def _article_date(art: ET.Element) -> tuple[Optional[str], Optional[str]]:
    """Read the publisher's ArticleDate, which states year, month and day."""
    date_el = art.find("Journal/ArticleDate")
    if date_el is None:
        date_el = art.find("ArticleDate")
    if date_el is None:
        return None, None
    return precision_from_parts(
        _int_text(date_el.find("Year")),
        _int_text(date_el.find("Month")),
        _int_text(date_el.find("Day")),
    )


def _entrez_history(pub_data: Optional[ET.Element]) -> tuple[Optional[str], Optional[str]]:
    """Return the date Entrez put the record online, plus the field it came from.

    ``PubStatus="entrez"`` is when the article entered the database, which is a
    different claim from when it was published, so nothing else here is used.
    """
    if pub_data is None:
        return None, None
    for pub_date in pub_data.findall("History/PubMedPubDate"):
        if pub_date.get("PubStatus") != "entrez":
            continue
        indexed, _ = precision_from_parts(
            _int_text(pub_date.find("Year")),
            _int_text(pub_date.find("Month")),
            _int_text(pub_date.find("Day")),
        )
        return (indexed, "entrez") if indexed else (None, None)
    return None, None


def _int_text(el: Optional[ET.Element]) -> Optional[int]:
    if el is None or not (el.text or "").strip().isdigit():
        return None
    return int(el.text.strip())
