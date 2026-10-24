"""FastAPI router for /api/compound/{name}."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from integrations import pubchem
from models.schemas import CompoundProfile

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/compound/{name}", response_model=CompoundProfile)
async def get_compound(name: str) -> CompoundProfile:
    """Fetch compound information from PubChem by name."""
    result = await pubchem.search_compound(name)
    if result is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "not_found", "detail": f"Compound '{name}' not found in PubChem."},
        )
    return result
