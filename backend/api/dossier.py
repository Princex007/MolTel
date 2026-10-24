"""FastAPI router for the /api/dossier endpoint."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from models.schemas import DossierRequest, DossierResponse
from services.research_orchestrator import ResearchOrchestrator

logger = logging.getLogger(__name__)

router = APIRouter()
_orchestrator = ResearchOrchestrator()


@router.post("/dossier", response_model=DossierResponse)
async def generate_dossier(request: DossierRequest) -> DossierResponse:
    """Generate a research dossier for the given query and search mode."""
    try:
        response = await _orchestrator.orchestrate(request.query, request.search_mode)
        return response
    except Exception as exc:  # noqa: BLE001
        logger.exception("Orchestration failed for query '%s'", request.query)
        raise HTTPException(
            status_code=500,
            detail={"error": "orchestration_failed", "detail": str(exc)},
        ) from exc
