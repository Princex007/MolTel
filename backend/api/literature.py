"""FastAPI router for /api/literature."""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Query

from integrations import europepmc, pubmed
from models.schemas import LiteratureView, LiteratureViewRequest, LiteratureViewResult
from services.evidence_normalizer import deduplicate_with_report, normalize_evidence_list
from services.literature_view import build_view

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/literature/views", response_model=LiteratureViewResult)
async def literature_view(request: LiteratureViewRequest) -> LiteratureViewResult:
    """Order and filter records already retrieved, without querying a source.

    The dossier holds every record a search returned, so switching a view or a
    filter is a re-ranking of that set. Doing it here keeps one implementation of
    each rule rather than a second one in the browser.
    """
    return build_view(request.items, request.query, request.view, request.filters)


@router.get("/literature", response_model=LiteratureViewResult)
async def search_literature(
    query: str = Query(..., description="Literature search query"),
    view: LiteratureView = Query(LiteratureView.most_relevant),
    max_results: int = Query(25, ge=1, le=100),
) -> LiteratureViewResult:
    """Search PubMed and Europe PMC, merge the records, and order them one way."""
    pubmed_results, epmc_results = await asyncio.gather(
        pubmed.search_literature(query, max_results),
        europepmc.search_literature(query, max_results),
        return_exceptions=True,
    )

    all_items: list[EvidenceItem] = []
    if not isinstance(pubmed_results, BaseException):
        all_items.extend(pubmed_results)
    else:
        logger.warning("PubMed search failed: %s", pubmed_results)

    if not isinstance(epmc_results, BaseException):
        all_items.extend(epmc_results)
    else:
        logger.warning("EuropePMC search failed: %s", epmc_results)

    normalized = normalize_evidence_list(all_items)
    deduped, deduplication = deduplicate_with_report(normalized)
    return build_view(deduped, query, view, deduplication=deduplication)
