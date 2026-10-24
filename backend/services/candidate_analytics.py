"""Candidate-level view of the retrieved registry records (spec §4.4, §5.1).

A trial is a registered study; a candidate is a product the registry names as an
intervention. The two are counted separately and never substituted for one
another. Sponsorship, label manufacture and development are three different
claims: the first two are source facts here, and the third is only ever stated
when a retrieved source states it — otherwise the record reads
"Developer not established".
"""

from __future__ import annotations

import re
from collections import Counter, OrderedDict
from typing import Iterable, Optional

from models.schemas import (
    CandidateAnalytics,
    CandidatePhaseBucket,
    CandidateRecord,
    ChartBucket,
    ClinicalTrial,
    CompanyPhaseCount,
    EvidenceItem,
    StatusBucket,
    TrialRetrievalMetadata,
)
from services import trial_taxonomy

# Registry intervention types that name a therapeutic product. Everything else
# (DEVICE, BEHAVIORAL, PROCEDURE, DIAGNOSTIC_TEST, …) is reported separately
# rather than dropped, because "not a candidate" is a statement about the source.
DRUG_LIKE_TYPES = frozenset(
    {"DRUG", "BIOLOGICAL", "DIETARY_SUPPLEMENT", "COMBINATION_PRODUCT"}
)

UNTYPED = "NOT_REPORTED"

# Comparators that the registry itself types as drug interventions. They stay in
# the candidate counts — dropping them would silently change what the registry
# states — but the number is reported so a reader does not take the list for a
# development pipeline. A name must be the comparator itself ("Placebo gel") or
# start a phrase about it, not a combination arm such as "placebo+metformin".
COMPARATOR_NAME = re.compile(
    r"^(placebo|sham|vehicle|saline|normal saline|0\.9% saline|5% dextrose|dextrose|d5w)"
    r"(?=$|[ /])"
)


def is_comparator(name: str) -> bool:
    return bool(COMPARATOR_NAME.match(normalize_name(name)))

# Shown wherever a label is reported, so a manufacturer is never read as the
# owner of the application or the product's developer.
LABEL_NOTE = (
    "openFDA reports the manufacturer named on this label and the application "
    "number; neither is treated as the developer."
)


def normalize_name(name: str) -> str:
    """Match key for a product name.

    Whitespace is collapsed and case is folded — nothing else. Salts, esters and
    formulations stay distinct because merging them would be a chemistry claim
    the registry does not make.
    """
    return re.sub(r"\s+", " ", str(name or "")).strip().casefold()


def _label_index(
    labels: Iterable[EvidenceItem],
) -> dict[str, tuple[Optional[str], Optional[str], Optional[str]]]:
    """Map product names to what a retrieved openFDA label states about them.

    The value is (manufacturer named on the label, application number, link).
    openFDA's label endpoint returns no application holder, so nothing here is
    reported as a marketing authorization holder.
    """
    index: dict[str, tuple[Optional[str], Optional[str], Optional[str]]] = {}
    for item in labels:
        meta = item.metadata or {}
        manufacturer = (meta.get("label_manufacturer") or "").strip() or None
        application = (meta.get("application_number") or "").strip() or None
        if not manufacturer and not application:
            continue
        names = list(meta.get("generic_names") or []) + list(meta.get("brand_names") or [])
        for name in names:
            key = normalize_name(name)
            if key and key not in index:
                index[key] = (manufacturer, application, item.url)
    return index


def _display_name(spellings: Counter[str]) -> str:
    """The most frequent spelling as the registry wrote it; ties go alphabetically."""
    if not spellings:
        return ""
    return sorted(spellings.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]


def _phase_of(trial: ClinicalTrial) -> str:
    return trial_taxonomy.phase_category(trial.phases)


class _Accumulator:
    """Everything the registry states about one product name across trials."""

    def __init__(self) -> None:
        self.spellings: Counter[str] = Counter()
        self.types: Counter[str] = Counter()
        self.trials: "OrderedDict[str, ClinicalTrial]" = OrderedDict()
        self.conditions: "OrderedDict[str, None]" = OrderedDict()
        self.sponsors: "OrderedDict[str, None]" = OrderedDict()
        self.collaborators: "OrderedDict[str, None]" = OrderedDict()

    def add(self, trial: ClinicalTrial, name: str, intervention_type: str) -> None:
        self.spellings[name] += 1
        self.types[intervention_type] += 1
        self.trials.setdefault(trial.nct_id, trial)
        for condition in trial.conditions:
            if condition and condition.strip():
                self.conditions.setdefault(condition.strip())
        if trial.sponsor:
            self.sponsors.setdefault(trial.sponsor)
        for collaborator in trial.collaborators:
            self.collaborators.setdefault(collaborator.name)


def compute_candidates(
    trials: list[ClinicalTrial],
    metadata: TrialRetrievalMetadata,
    labels: Optional[list[EvidenceItem]] = None,
) -> CandidateAnalytics:
    """Build candidate records and charts from the same deduplicated trial list."""
    label_index = _label_index(labels or [])
    accumulators: dict[str, _Accumulator] = {}
    non_drug: Counter[str] = Counter()
    trials_without_candidate = 0
    candidate_trial_ids: set[str] = set()

    for trial in trials:
        named = [d for d in trial.intervention_details if normalize_name(d.name)]
        drug_like = [d for d in named if (d.type or "").upper() in DRUG_LIKE_TYPES]
        for detail in named:
            if detail not in drug_like:
                non_drug[(detail.type or "").strip().upper() or UNTYPED] += 1
        if not drug_like:
            trials_without_candidate += 1
            continue
        candidate_trial_ids.add(trial.nct_id)
        for detail in drug_like:
            acc = accumulators.setdefault(normalize_name(detail.name), _Accumulator())
            acc.add(trial, detail.name.strip(), (detail.type or "").strip().upper())

    records: list[CandidateRecord] = []
    by_phase: Counter[str] = Counter()
    ongoing_by_phase: Counter[str] = Counter()
    by_company: Counter[str] = Counter()
    company_phase: dict[tuple[str, str, str], int] = {}

    for key, acc in accumulators.items():
        trial_list = list(acc.trials.values())
        phase_ids: "OrderedDict[str, list[str]]" = OrderedDict()
        ongoing_phases: set[str] = set()
        status_counts: Counter[str] = Counter()
        status_categories: dict[str, str] = {}
        ongoing = 0
        starts: list[str] = []
        completions: list[str] = []
        updates: list[str] = []
        links: list[str] = []

        for trial in trial_list:
            phase = _phase_of(trial)
            ids = phase_ids.setdefault(phase, [])
            if trial.nct_id not in ids:
                ids.append(trial.nct_id)
            if trial.ongoing:
                ongoing += 1
                ongoing_phases.add(phase)
            status = trial.status or trial.overall_status or "Not reported"
            status_counts[status] += 1
            status_categories[status] = trial_taxonomy.status_category_label(
                trial.overall_status
            )
            if trial.start_date:
                starts.append(trial.start_date)
            if trial.completion_date:
                completions.append(trial.completion_date)
            if trial.last_update_date:
                updates.append(trial.last_update_date)
            if trial.source_url and trial.source_url not in links:
                links.append(trial.source_url)

        buckets = sorted(
            (
                CandidatePhaseBucket(
                    phase=phase, phase_category=phase, trials=len(ids), nct_ids=ids
                )
                for phase, ids in phase_ids.items()
            ),
            key=lambda b: trial_taxonomy.phase_sort_key(b.phase),
        )
        real_phases = [
            b.phase
            for b in buckets
            if b.phase not in (trial_taxonomy.UNKNOWN_PHASE, "Not Applicable")
        ]
        name = _display_name(acc.spellings)
        label = label_index.get(key)
        manufacturer = label[0] if label else None
        application = label[1] if label else None
        record = CandidateRecord(
            name=name,
            matched_names=sorted(acc.spellings),
            intervention_types=sorted(acc.types),
            trials=len(trial_list),
            nct_ids=[t.nct_id for t in trial_list],
            phases=buckets,
            highest_phase=(
                max(real_phases, key=trial_taxonomy.phase_sort_key) if real_phases else None
            ),
            statuses=[
                StatusBucket(label=s, count=c, category=status_categories[s])
                for s, c in sorted(status_counts.items(), key=lambda kv: (-kv[1], kv[0]))
            ],
            ongoing_trials=ongoing,
            conditions=list(acc.conditions),
            sponsors=list(acc.sponsors),
            collaborators=list(acc.collaborators),
            fda_application_number=application,
            label_manufacturer=manufacturer,
            label_source_url=label[2] if label else None,
            developer=None,
            developer_note="Developer not established",
            label_note=LABEL_NOTE if label else "",
            start_date=min(starts) if starts else None,
            completion_date=max(completions) if completions else None,
            last_update_date=max(updates) if updates else None,
            retrieved_at=metadata.retrieved_at,
            source_links=links,
        )
        records.append(record)

        for bucket in buckets:
            by_phase[bucket.phase] += 1
        for phase in ongoing_phases:
            ongoing_by_phase[phase] += 1
        companies = _companies(record)
        for company, _ in companies:
            by_company[company] += 1
        for phase in {b.phase for b in buckets}:
            for company, attribution in companies:
                company_phase[(company, phase, attribution)] = (
                    company_phase.get((company, phase, attribution), 0) + 1
                    )

    records.sort(key=lambda r: (-r.trials, normalize_name(r.name)))

    return CandidateAnalytics(
        distinct_candidates=len(records),
        candidate_trials_considered=len(candidate_trial_ids),
        trials_without_named_intervention=trials_without_candidate,
        candidates_by_phase=_phase_buckets(by_phase),
        ongoing_candidates_by_phase=_phase_buckets(ongoing_by_phase),
        candidates_by_company=[
            ChartBucket(label=company, count=count)
            for company, count in sorted(by_company.items(), key=lambda kv: (-kv[1], kv[0]))
        ],
        company_by_phase=[
            CompanyPhaseCount(
                company=company, phase=phase, attribution=attribution, candidates=count
            )
            for (company, phase, attribution), count in sorted(
                company_phase.items(),
                key=lambda kv: (-kv[1], kv[0][0], trial_taxonomy.phase_sort_key(kv[0][1])),
            )
        ],
        candidates_with_established_developer=sum(1 for r in records if r.developer),
        comparator_candidates=sum(1 for r in records if is_comparator(r.name)),
        candidates_with_openfda_label=sum(
            1 for r in records if r.label_manufacturer or r.fda_application_number
        ),
        non_drug_intervention_types=[
            ChartBucket(
                label=(
                    "No type reported by the registry"
                    if code == UNTYPED
                    else code.replace("_", " ").title()
                ),
                count=count,
            )
            for code, count in sorted(non_drug.items(), key=lambda kv: (-kv[1], kv[0]))
        ],
        records=records,
        metadata=metadata,
    )


def _phase_buckets(counter: Counter[str]) -> list[ChartBucket]:
    return [
        ChartBucket(label=phase, count=count)
        for phase, count in sorted(
            counter.items(), key=lambda kv: trial_taxonomy.phase_sort_key(kv[0])
        )
    ]


def _companies(record: CandidateRecord) -> list[tuple[str, str]]:
    """Companies a retrieved source names for this candidate, with that source.

    Deduplicated by name: a company that is both a trial sponsor and a label
    manufacturer is one entry, so no candidate is counted twice for it.
    """
    attributions: "OrderedDict[str, list[str]]" = OrderedDict()
    if record.label_manufacturer:
        attributions.setdefault(record.label_manufacturer, []).append(
            "Manufacturer named on an openFDA label"
        )
    for sponsor in record.sponsors:
        attributions.setdefault(sponsor, []).append(
            "Lead sponsor of a trial studying this product"
        )
    return [(company, "; ".join(dict.fromkeys(parts))) for company, parts in attributions.items()]
