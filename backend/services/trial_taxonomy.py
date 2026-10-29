"""Centralised ClinicalTrials.gov status and phase classification.

The registry returns SCREAMING_SNAKE_CASE codes. Every mapping in this module is
deliberately transparent and total: an unrecognised value is never dropped or
silently folded into a neighbouring bucket, it is preserved and reported as
"Other or unclear" / "Unknown or not reported" so the dashboard cannot overstate
what the source actually said.
"""

from __future__ import annotations

from typing import Iterable, Optional

# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------

STATUS_LABELS: dict[str, str] = {
    "ACTIVE_NOT_RECRUITING": "Active, not recruiting",
    "AVAILABLE": "Available",
    "COMPLETED": "Completed",
    "ENROLLING_BY_INVITATION": "Enrolling by invitation",
    "NOT_YET_RECRUITING": "Not yet recruiting",
    "RECRUITING": "Recruiting",
    "SUSPENDED": "Suspended",
    "TEMPORARILY_NOT_AVAILABLE": "Temporarily not available",
    "TERMINATED": "Terminated",
    "UNKNOWN": "Unknown",
    "WITHDRAWN": "Withdrawn",
}

# Dashboard categories. Each maps to an explicit set of registry statuses so the
# rules behind every count on the UI are auditable from one place.
STATUS_CATEGORY_LABELS: dict[str, str] = {
    "currently_recruiting": "Currently recruiting",
    "ongoing_not_recruiting": "Ongoing, not currently recruiting",
    "not_yet_started": "Not yet started",
    "paused": "Paused",
    "completed": "Completed",
    "discontinued": "Discontinued",
    "other_or_unclear": "Other or unclear",
}

_STATUS_TO_CATEGORY: dict[str, str] = {
    "RECRUITING": "currently_recruiting",
    "ENROLLING_BY_INVITATION": "currently_recruiting",
    "ACTIVE_NOT_RECRUITING": "ongoing_not_recruiting",
    "NOT_YET_RECRUITING": "not_yet_started",
    "SUSPENDED": "paused",
    "COMPLETED": "completed",
    "TERMINATED": "discontinued",
    "WITHDRAWN": "discontinued",
    "UNKNOWN": "other_or_unclear",
    # Not assigned a research meaning by the dashboard rules, so kept explicit.
    "AVAILABLE": "other_or_unclear",
    "TEMPORARILY_NOT_AVAILABLE": "other_or_unclear",
}

# Reverse lookup so callers that only have a human label still classify correctly.
_LABEL_TO_CODE = {label.upper(): code for code, label in STATUS_LABELS.items()}

# The three statuses the spec defines as "ongoing" for chart purposes.
ONGOING_STATUSES = frozenset(
    {"RECRUITING", "ENROLLING_BY_INVITATION", "ACTIVE_NOT_RECRUITING"}
)

# Registry arm roles that mean "this arm receives the product as a comparator".
# OTHER is deliberately absent: the registry does not say what an OTHER arm is, so
# calling it a comparator would be a claim the source never makes.
COMPARATOR_ROLES = frozenset(
    {"PLACEBO_COMPARATOR", "ACTIVE_COMPARATOR", "SHAM_COMPARATOR"}
)
# Roles that state the arm is a masked control, used when a placebo arm is asked
# for by name rather than as a comparator.
MASKED_ROLES = frozenset({"PLACEBO_COMPARATOR", "SHAM_COMPARATOR"})

# One derived group: the single place its membership is declared, so a heading,
# a chart legend and a KPI tile cannot each describe it differently.
RECRUITING_CATEGORY = "currently_recruiting"
ONGOING_CATEGORY = "ongoing"

_CATEGORY_MEMBERS: dict[str, tuple[str, ...]] = {
    category: tuple(
        code
        for code, mapped in _STATUS_TO_CATEGORY.items()
        if mapped == category
    )
    for category in STATUS_CATEGORY_LABELS
}


def status_group_members(category: str) -> tuple[str, ...]:
    """Exact registry statuses folded into one dashboard category.

    Empty for a category the map never assigns, so a derived group can never
    claim members that no record can reach.
    """
    return _CATEGORY_MEMBERS.get(category, ())


def status_group_definition(category: str) -> str:
    """The mapping sentence shown beside every derived count."""
    members = status_group_members(category)
    label = STATUS_CATEGORY_LABELS.get(category, category)
    if not members:
        return f"{label}: no registry status maps here in this build."
    names = ", ".join(STATUS_LABELS.get(code, code) for code in members)
    return f"{label} = registry statuses: {names}."


def ongoing_definition() -> str:
    members = ", ".join(STATUS_LABELS[s] for s in sorted(ONGOING_STATUSES))
    return (
        f"Ongoing = registry status is one of: {members}. It is a re-cut of the "
        "same records and is never added to the raw status totals."
    )


def normalize_status(value: Optional[str]) -> str:
    """Return the registry code for a status, or the upper-cased input if unknown."""
    if not value:
        return ""
    key = value.strip().upper().replace(", ", "_").replace(" ", "_").replace("-", "_")
    if key in _STATUS_TO_CATEGORY:
        return key
    return _LABEL_TO_CODE.get(value.strip().upper(), key)


def status_label(value: Optional[str]) -> Optional[str]:
    """Human-readable status, preserving unrecognised values rather than discarding."""
    code = normalize_status(value)
    if not code:
        return None
    return STATUS_LABELS.get(code, code.replace("_", " ").title())


def status_category(value: Optional[str]) -> str:
    """Dashboard category for a status; unrecognised codes land in other_or_unclear."""
    return _STATUS_TO_CATEGORY.get(normalize_status(value), "other_or_unclear")


def status_category_label(value: Optional[str]) -> str:
    return STATUS_CATEGORY_LABELS[status_category(value)]


def is_ongoing(value: Optional[str]) -> bool:
    """Ongoing means recruiting, enrolling by invitation, or active not recruiting."""
    return normalize_status(value) in ONGOING_STATUSES


def is_recruiting(value: Optional[str]) -> bool:
    return status_category(value) == "currently_recruiting"


# ---------------------------------------------------------------------------
# Phase
# ---------------------------------------------------------------------------

PHASE_LABELS: dict[str, str] = {
    "EARLY_PHASE1": "Early Phase 1",
    "PHASE1": "Phase 1",
    "PHASE1/PHASE2": "Phase 1/2",
    "PHASE2": "Phase 2",
    "PHASE2/PHASE3": "Phase 2/3",
    "PHASE3": "Phase 3",
    "PHASE4": "Phase 4",
    "NA": "Not Applicable",
}

UNKNOWN_PHASE = "Unknown / Not Reported"

_PHASE_ORDER = [
    "Early Phase 1",
    "Phase 1",
    "Phase 1/2",
    "Phase 2",
    "Phase 2/3",
    "Phase 3",
    "Phase 4",
    "Not Applicable",
    UNKNOWN_PHASE,
]

_LABEL_TO_PHASE = {label.upper(): label for label in PHASE_LABELS.values()}


def normalize_phase(value: Optional[str]) -> str:
    """Return a display phase label, preserving combined phases as their own category."""
    if not value:
        return UNKNOWN_PHASE
    code = value.strip().upper().replace(" ", "")
    if code in PHASE_LABELS:
        return PHASE_LABELS[code]
    if code in _LABEL_TO_PHASE:
        return _LABEL_TO_PHASE[code]
    # An unrecognised (e.g. newly introduced) phase is reported, not invented.
    return value.strip().title()


def phase_label(values: Iterable[Optional[str]]) -> Optional[str]:
    """Join the phases of one study without collapsing a combined phase."""
    labels = [normalize_phase(v) for v in values if v and v.strip()]
    if not labels:
        return None
    # A single "PHASE1/PHASE2" entry already carries the combination.
    return ", ".join(dict.fromkeys(labels))


def phase_category(values: Iterable[Optional[str]]) -> str:
    """Single charting bucket for a study.

    Studies reporting several distinct phases keep a combined label rather than
    being assigned arbitrarily to one phase.
    """
    labels = [normalize_phase(v) for v in values if v and v.strip()]
    if not labels:
        return UNKNOWN_PHASE
    if len(labels) == 1:
        return labels[0]
    return " + ".join(labels)


def phase_sort_key(label: str) -> tuple[int, str]:
    """Order chart categories by clinical progression, unknown last."""
    try:
        return (_PHASE_ORDER.index(label), label)
    except ValueError:
        return (len(_PHASE_ORDER), label)


def has_known_phase(values: Iterable[Optional[str]]) -> bool:
    return phase_category(values) != UNKNOWN_PHASE
