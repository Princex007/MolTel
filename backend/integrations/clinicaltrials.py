"""ClinicalTrials.gov v2 API integration."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from models.schemas import (
    ClinicalTrial,
    TrialArmGroup,
    TrialCollaborator,
    TrialIntervention,
    TrialOutcome,
    TrialRetrievalMetadata,
)
from services import trial_taxonomy
from utils.http import safe_get

logger = logging.getLogger(__name__)

BASE_URL = "https://clinicaltrials.gov/api/v2"

_STUDY_TYPE_LABELS = {
    "INTERVENTIONAL": "Interventional",
    "OBSERVATIONAL": "Observational",
    "EXPANDED_ACCESS": "Expanded access",
}


def _humanize(value: str, labels: dict[str, str]) -> str:
    """Map a registry code to its label, falling back to title case."""
    if not value:
        return ""
    return labels.get(value.strip().upper(), value.replace("_", " ").title())


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _date_text(module: dict, key: str) -> Optional[str]:
    """Read a `*DateStruct.date` value without inventing one when absent.

    The registry reports partial dates ("2003-01", "2003"), which are kept
    exactly as supplied rather than padded to a fabricated day.
    """
    struct = module.get(key)
    if isinstance(struct, dict):
        value = struct.get("date")
    else:
        value = struct
    value = (value or "").strip()
    return value or None


async def fetch_trials(
    query: str, page_size: int = 50
) -> tuple[list[ClinicalTrial], TrialRetrievalMetadata]:
    """Search the registry and return deduplicated records plus retrieval metadata."""
    url = f"{BASE_URL}/studies"
    params = {
        "query.term": query,
        "pageSize": str(min(max(page_size, 1), 100)),
        "format": "json",
    }
    data = await safe_get(url, params=params)

    retrieved_at = _now_iso()
    if data is None:
        # A failed lookup is reported as such; the caller must not read it as
        # "no trials exist".
        return [], TrialRetrievalMetadata(
            query=query,
            retrieved_at=retrieved_at,
            partial=True,
            source_reached=False,
            note="ClinicalTrials.gov could not be reached, so no trial records are available.",
        )

    seen: set[str] = set()
    trials: list[ClinicalTrial] = []
    for study in data.get("studies", []):
        trial = _parse_study(study, retrieved_at)
        if trial and trial.nct_id not in seen:
            seen.add(trial.nct_id)
            trials.append(trial)

    next_token = data.get("nextPageToken")
    metadata = TrialRetrievalMetadata(
        query=query,
        retrieved_at=retrieved_at,
        records_returned=len(trials),
        has_more=bool(next_token),
        partial=bool(next_token),
        note=(
            f"Showing the {len(trials)} most relevant registry records for this "
            "search. Additional results are available, so these counts are not the "
            "complete universe of trials for this topic."
        )
        if next_token
        else (
            f"All {len(trials)} registry records matching this search were retrieved."
            if trials
            else "The search returned no registered studies. This does not establish "
            "that no clinical trials exist for this topic."
        ),
    )
    return trials, metadata


async def search_trials(query: str, max_results: int = 50) -> list[ClinicalTrial]:
    """Search ClinicalTrials.gov and return a list of ClinicalTrial objects."""
    trials, _ = await fetch_trials(query, page_size=max_results)
    return trials


_OUTCOME_MEASURE_CAP = 20


def _parse_outcomes(module: dict) -> tuple[list[TrialOutcome], list[str]]:
    """Read the outcome list the registry publishes, with its stated time frames.

    Records can list dozens of secondary measures, so only the first measures are
    kept for reading, while every distinct time frame is retained: the duration
    check needs the full set of time points a study actually reads, and dropping
    one would turn a supported claim into a flagged one.
    """
    outcomes: list[TrialOutcome] = []
    frames: list[str] = []
    for category, key in (
        ("primary", "primaryOutcomes"),
        ("secondary", "secondaryOutcomes"),
    ):
        for item in module.get(key) or []:
            if not isinstance(item, dict):
                continue
            measure = (item.get("measure") or "").strip()
            if not measure:
                continue
            if len(outcomes) < _OUTCOME_MEASURE_CAP:
                outcomes.append(TrialOutcome(measure=measure, category=category))
            frame = (item.get("timeFrame") or "").strip()
            if frame and frame not in frames:
                frames.append(frame)
    return outcomes, frames


def _parse_study(study: dict, retrieved_at: str) -> ClinicalTrial | None:
    """Parse a single study dict from ClinicalTrials.gov v2 API."""
    try:
        protocol = study.get("protocolSection", {})
        id_module = protocol.get("identificationModule", {})
        status_module = protocol.get("statusModule", {})
        design_module = protocol.get("designModule", {})
        cond_module = protocol.get("conditionsModule", {})
        arms_module = protocol.get("armsInterventionsModule", {})
        outcomes_module = protocol.get("outcomesModule", {})
        sponsor_module = protocol.get("sponsorCollaboratorsModule", {})
        desc_module = protocol.get("descriptionModule", {})

        nct_id: str = id_module.get("nctId", "")
        if not nct_id:
            return None

        title: str = id_module.get("briefTitle", "")
        raw_status = status_module.get("overallStatus", "")
        status = trial_taxonomy.status_label(raw_status)
        study_type = _humanize(design_module.get("studyType", ""), _STUDY_TYPE_LABELS)

        phases_list: list[str] = [
            p for p in design_module.get("phases", []) if p and str(p).strip()
        ]
        phase = trial_taxonomy.phase_label(phases_list)

        conditions: list[str] = cond_module.get("conditions", []) or []
        raw_interventions = [
            i for i in arms_module.get("interventions", []) if isinstance(i, dict) and i.get("name")
        ]
        interventions: list[str] = [i["name"].strip() for i in raw_interventions]
        # The registry states an intervention's role only through the arm it sits
        # in, so the arm list is read first and each intervention is linked to the
        # arm types that name it. A role is never guessed from the name wording.
        arm_groups: list[TrialArmGroup] = [
            TrialArmGroup(
                label=(group.get("label") or "").strip(),
                type=(group.get("type") or "").strip().upper() or None,
                intervention_names=[
                    str(n).strip()
                    for n in (group.get("interventionNames") or [])
                    if str(n).strip()
                ],
            )
            for group in arms_module.get("armGroups", []) or []
            if isinstance(group, dict) and (group.get("label") or "").strip()
        ]
        # armGroupLabels links intervention -> arm; a record can also state the
        # link only on the arm side, so both directions are honoured.
        role_by_label: dict[str, str] = {
            group.label: group.type for group in arm_groups if group.type
        }

        def _role_for(detail: dict, labels: list[str]) -> Optional[str]:
            # The arm lists interventions as "Drug: Semaglutide"; the case the
            # registry picks for the type is not a second identifier.
            own = f"{(detail.get('type') or '').strip()}: {detail['name'].strip()}".casefold()
            for group in arm_groups:
                if any(own == listed.casefold() for listed in group.intervention_names):
                    return group.type
            for label in labels:
                if label in role_by_label:
                    return role_by_label[label]
            return None

        intervention_details: list[TrialIntervention] = []
        for i in raw_interventions:
            labels = [
                str(label).strip()
                for label in (i.get("armGroupLabels") or [])
                if str(label).strip()
            ]
            intervention_details.append(
                TrialIntervention(
                    name=i["name"].strip(),
                    type=(i.get("type") or "").strip().upper() or None,
                    description=(i.get("description") or "").strip() or None,
                    arm_group_labels=labels,
                    role=_role_for(i, labels),
                )
            )
        outcomes, time_frames = _parse_outcomes(outcomes_module)
        sponsor: str = sponsor_module.get("leadSponsor", {}).get("name", "")
        # Collaborators are recorded by the registry as partners of the sponsor.
        # They are kept because they are source facts, not because they identify
        # a developer.
        collaborators: list[TrialCollaborator] = [
            TrialCollaborator(
                name=c.get("name", "").strip(),
                registry_class=(c.get("class") or "").strip().upper() or None,
            )
            for c in sponsor_module.get("collaborators", []) or []
            if isinstance(c, dict) and c.get("name")
        ]

        enrollment = design_module.get("enrollmentInfo", {}) or {}
        enrollment_count = enrollment.get("count")
        url = f"https://clinicaltrials.gov/study/{nct_id}"

        return ClinicalTrial(
            nct_id=nct_id,
            title=title or None,
            status=status or None,
            phase=phase,
            conditions=conditions,
            interventions=interventions,
            intervention_details=intervention_details,
            arm_groups=arm_groups,
            collaborators=collaborators,
            outcomes=outcomes,
            outcome_time_frames=time_frames,
            sponsor=sponsor or None,
            study_type=study_type or None,
            url=url,
            overall_status=raw_status or None,
            phases=phases_list,
            status_category=trial_taxonomy.status_category(raw_status),
            status_category_label=trial_taxonomy.status_category_label(raw_status),
            ongoing=trial_taxonomy.is_ongoing(raw_status),
            brief_summary=(desc_module.get("briefSummary") or "").strip() or None,
            start_date=_date_text(status_module, "startDateStruct"),
            primary_completion_date=_date_text(status_module, "primaryCompletionDateStruct"),
            completion_date=_date_text(status_module, "completionDateStruct"),
            enrollment_count=enrollment_count if isinstance(enrollment_count, int) else None,
            enrollment_type=enrollment.get("type") or None,
            last_update_date=(status_module.get("lastUpdateSubmitDate") or "").strip() or None,
            source_url=url,
            retrieved_at=retrieved_at,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("ClinicalTrials: error parsing study: %s", exc)
        return None
