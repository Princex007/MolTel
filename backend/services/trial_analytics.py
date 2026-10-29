"""Deterministic clinical-trial analytics for the landscape dashboard.

Every number here is computed from the deduplicated registry records supplied by
the caller. The model is never asked to count trials, and records that lack a
field are reported as missing rather than defaulted to a plausible value.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Optional

from models.schemas import (
    ChartBucket,
    ClinicalTrial,
    StatusBucket,
    StatusGroup,
    TrialAnalytics,
    TrialRetrievalMetadata,
    TrialStartPeriod,
)
from services import trial_taxonomy

_DATE = re.compile(r"^(\d{4})(?:-(\d{2}))?(?:-(\d{2}))?$")

# Below this many dated studies a timeline says more about the sample than the
# landscape, so the chart is omitted with an explanation.
_MIN_TIMELINE_RECORDS = 3
_MONTH_SPAN_LIMIT = 18


def _parse_date(value: Optional[str]) -> Optional[tuple[int, Optional[int]]]:
    """Return (year, month or None) for a registry date, or None if unusable."""
    if not value:
        return None
    match = _DATE.match(value.strip())
    if not match:
        return None
    year = int(match.group(1))
    month = int(match.group(2)) if match.group(2) else None
    if month is not None and not 1 <= month <= 12:
        return None
    return year, month


def _phase_of(trial: ClinicalTrial) -> str:
    if trial.phase_category:
        return trial.phase_category
    return trial_taxonomy.phase_category(trial.phases or ([trial.phase] if trial.phase else []))


def compute_analytics(
    trials: list[ClinicalTrial], metadata: TrialRetrievalMetadata
) -> TrialAnalytics:
    """Aggregate trial records into chart-ready buckets."""
    deduped: dict[str, ClinicalTrial] = {}
    for trial in trials:
        deduped.setdefault(trial.nct_id, trial)
    records = list(deduped.values())

    analytics = TrialAnalytics(metadata=metadata, total_trials=len(records))

    phase_counts: Counter[str] = Counter()
    ongoing_phase_counts: Counter[str] = Counter()
    status_counts: Counter[tuple[str, str]] = Counter()
    category_counts: Counter[str] = Counter()

    for trial in records:
        raw = trial.overall_status or trial.status
        code = trial_taxonomy.normalize_status(raw)
        category = trial_taxonomy.status_category(raw)
        label = trial_taxonomy.status_label(raw) or "Unknown"
        status_counts[(label, category)] += 1
        category_counts[category] += 1
        phase_counts[_phase_of(trial)] += 1

        # One counter per registry status, read off the code rather than the
        # dashboard category: an "Enrolling by invitation" study is not silently
        # reported as "Recruiting", and the category it belongs to is stated
        # next to its count instead of being assumed from the heading.
        if code == "RECRUITING":
            analytics.recruiting_trials += 1
        elif code == "ENROLLING_BY_INVITATION":
            analytics.enrolling_by_invitation_trials += 1

        if category == "currently_recruiting":
            analytics.currently_recruiting_trials += 1
        elif category == "ongoing_not_recruiting":
            # Reported separately so the reader can see that Ongoing is this
            # count plus the recruiting count, rather than a fourth bucket.
            analytics.active_not_recruiting_trials += 1
        elif category == "not_yet_started":
            analytics.not_yet_recruiting_trials += 1
        elif category == "paused":
            analytics.paused_trials += 1
        elif category == "completed":
            analytics.completed_trials += 1
        elif category == "discontinued":
            analytics.discontinued_trials += 1
        else:
            analytics.other_status_trials += 1

        if trial_taxonomy.is_ongoing(raw):
            analytics.ongoing_trials += 1
            ongoing_phase_counts[_phase_of(trial)] += 1

        if _phase_of(trial) == trial_taxonomy.UNKNOWN_PHASE:
            analytics.trials_with_unreported_phase += 1

    # The derived groups carry their own membership so a heading can never drift
    # from the arithmetic that produced the number next to it.
    analytics.status_groups = [
        StatusGroup(
            category=category,
            label=trial_taxonomy.STATUS_CATEGORY_LABELS[category],
            definition=trial_taxonomy.status_group_definition(category),
            registry_statuses=[
                trial_taxonomy.STATUS_LABELS.get(code, code)
                for code in trial_taxonomy.status_group_members(category)
            ],
            count=category_counts[category],
        )
        for category in trial_taxonomy.STATUS_CATEGORY_LABELS
        if category_counts[category]
    ]
    analytics.ongoing_definition = trial_taxonomy.ongoing_definition()
    # Every record lands in exactly one dashboard category, so these rows are a
    # partition; a derived group such as Ongoing is a re-cut and stays out.
    analytics.exclusive_status_total = sum(category_counts.values())
    analytics.statuses_reconcile = analytics.exclusive_status_total == len(records)

    analytics.trials_by_phase = [
        ChartBucket(label=label, count=count)
        for label, count in sorted(
            phase_counts.items(), key=lambda kv: (trial_taxonomy.phase_sort_key(kv[0]), -kv[1])
        )
    ]
    analytics.ongoing_trials_by_phase = [
        ChartBucket(label=label, count=count)
        for label, count in sorted(
            ongoing_phase_counts.items(),
            key=lambda kv: (trial_taxonomy.phase_sort_key(kv[0]), -kv[1]),
        )
    ]
    analytics.trials_by_status = [
        StatusBucket(label=label, count=count, category=category)
        for (label, category), count in sorted(
            status_counts.items(), key=lambda kv: (-kv[1], kv[0][0])
        )
    ]

    _attach_timeline(records, analytics)
    return analytics


def _attach_timeline(records: list[ClinicalTrial], analytics: TrialAnalytics) -> None:
    """Build the start-date timeline, or explain why one is not meaningful."""
    parsed: list[tuple[int, Optional[int]]] = []
    for trial in records:
        value = _parse_date(trial.start_date)
        if value:
            parsed.append(value)

    analytics.excluded_from_timeline_count = len(records) - len(parsed)

    if len(parsed) < _MIN_TIMELINE_RECORDS:
        analytics.timeline_omitted_reason = (
            f"Only {len(parsed)} of {len(records)} retrieved records carry a usable "
            "study start date, which is too few for a meaningful timeline."
        )
        return

    dated_months = [p for p in parsed if p[1] is not None]
    span_months = _span_in_months(parsed)

    if len(dated_months) == len(parsed) and span_months <= _MONTH_SPAN_LIMIT:
        buckets = Counter(f"{y:04d}-{m:02d}" for y, m in dated_months)
        analytics.timeline_granularity = "month"
    else:
        buckets = Counter(f"{y:04d}" for y, _ in parsed)
        analytics.timeline_granularity = "year"

    analytics.trial_starts_by_period = [
        TrialStartPeriod(period=period, count=count)
        for period, count in sorted(buckets.items())
    ]


def _span_in_months(parsed: list[tuple[int, Optional[int]]]) -> int:
    months = [
        year * 12 + (month or 1) for year, month in parsed
    ]
    return max(months) - min(months) + 1 if months else 0
