"""FastAPI router for /api/trials."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Query

from integrations import clinicaltrials
from models.schemas import TrialsResponse
from services import trial_taxonomy
from services.candidate_analytics import compute_candidates
from services.trial_analytics import compute_analytics

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/trials", response_model=TrialsResponse)
async def search_trials(
    query: str = Query(..., description="Clinical trials search query"),
    status: str = Query("", description="Filter by registry status code or label"),
    phase: str = Query("", description="Filter by phase, e.g. PHASE2 or 'Phase 2'"),
    study_type: str = Query("", description="Filter by study type, e.g. INTERVENTIONAL"),
    condition: str = Query("", description="Filter by condition text"),
) -> TrialsResponse:
    """Search ClinicalTrials.gov and return records plus deterministic analytics.

    Analytics are always computed over the unfiltered result set so the charts
    describe the retrieved landscape; the `trials` list carries the filter the
    user asked for. When the registry could not be consulted no analytics are
    returned at all — zero-filled charts would read as "no trials exist".
    """
    trials, metadata = await clinicaltrials.fetch_trials(query)
    analytics = compute_analytics(trials, metadata) if metadata.source_reached else None
    # This endpoint does not consult openFDA, so no label facts are available
    # here; candidate records say "Developer not established" accordingly.
    candidate_analytics = (
        compute_candidates(trials, metadata) if metadata.source_reached else None
    )

    return TrialsResponse(
        query=query,
        trials=_apply_filters(trials, status, phase, study_type, condition),
        metadata=metadata,
        analytics=analytics,
        candidate_analytics=candidate_analytics,
    )


def _apply_filters(
    trials: list,
    status: str,
    phase: str,
    study_type: str,
    condition: str,
) -> list:
    """Filter records on the fields the dashboard exposes, keeping the full set
    when no filter is given."""
    if not any([status, phase, study_type, condition]):
        return trials

    wanted_status = trial_taxonomy.normalize_status(status) if status else ""
    wanted_phase = trial_taxonomy.normalize_phase(phase) if phase else ""
    wanted_type = study_type.strip().upper() if study_type else ""
    wanted_condition = condition.strip().lower() if condition else ""

    result = []
    for trial in trials:
        if wanted_status and trial_taxonomy.normalize_status(
            trial.overall_status or trial.status
        ) != wanted_status:
            continue
        if wanted_phase:
            trial_phases = trial.phases or ([trial.phase] if trial.phase else [])
            normalized = {trial_taxonomy.normalize_phase(p) for p in trial_phases}
            # A combined bucket such as "Phase 1 + Phase 2" is one category of
            # its own, so the study's charting category is matched too.
            if (
                wanted_phase not in normalized
                and wanted_phase != trial_taxonomy.phase_category(trial_phases)
            ):
                continue
        if wanted_type and (trial.study_type or "").upper().replace(" ", "_") != wanted_type:
            continue
        if wanted_condition and not any(
            wanted_condition in c.lower() for c in trial.conditions
        ):
            continue
        result.append(trial)
    return result
