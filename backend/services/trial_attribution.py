"""Which retrieved trials actually name the queried product, and how we know.

The registry search matches wording, not molecules: a study is returned because a
term appears somewhere in its record, which does not make that term one of the
things the study administers. This module reads only the structured
intervention fields the registry supplies — never a title keyword — and sorts
every record into one of four named categories so a "studies of this product"
count cannot quietly include studies that merely mention it, placebos, procedures
or somebody else's investigational drug.

Nothing here is specific to any one compound: the categories are defined against
the query string the caller searched with.
"""

from __future__ import annotations

import re
from typing import Iterable, Optional

from models.schemas import (
    AttributionCategory,
    ClinicalTrial,
    QueryAttribution,
    QueryAttributionSummary,
    TrialIntervention,
)
from services.candidate_analytics import DRUG_LIKE_TYPES, normalize_name
from services.trial_taxonomy import COMPARATOR_ROLES, MASKED_ROLES

# Four named categories, mutually exclusive per trial. The first two are the only
# ones that may be counted as studies of the queried product.
DIRECT = "direct"
COMPARATOR_OR_COMBINATION = "comparator_or_combination"
RELATED_NOT_NAMED = "related_not_named"
NOT_DEMONSTRABLY_RELEVANT = "not_demonstrably_relevant"

CATEGORY_LABELS: dict[str, str] = {
    DIRECT: "The queried product is a registered intervention",
    COMPARATOR_OR_COMBINATION: (
        "The queried product is registered, as a comparator, background or "
        "component of a combination product"
    ),
    RELATED_NOT_NAMED: (
        "Related, but the queried product is not a registered intervention here — "
        "the link comes from a co-registered product or from wording, not from this "
        "record's own intervention list"
    ),
    NOT_DEMONSTRABLY_RELEVANT: "No structured evidence of a relationship to the query",
}

CATEGORY_BASIS: dict[str, str] = {
    DIRECT: "Registry armsInterventionsModule lists the queried name as an intervention.",
    COMPARATOR_OR_COMBINATION: (
        "Registry lists the queried name as an intervention whose registered arm "
        "role is a comparator, or inside a combination product name."
    ),
    RELATED_NOT_NAMED: (
        "The queried name appears only in this record's condition, title or summary "
        "wording, never among its interventions, so no study of the product is "
        "established."
    ),
    NOT_DEMONSTRABLY_RELEVANT: (
        "The queried name appears in no structured field the registry returned for "
        "this record, so its relevance is not established by these records."
    ),
}

# A combination product names more than one substance in one intervention string.
_COMBINATION = re.compile(r"\s*(?:\+|/|;|\b(?:with|plus|and)\b)\s+", re.I)

_WORD = re.compile(r"[a-z0-9]+")


def _words(text: str) -> list[str]:
    return _WORD.findall(normalize_name(text))


def names_query(name: str, query_words: list[str]) -> bool:
    """Whether a registry value contains the queried product as a word sequence.

    Word-boundary matching on the source spelling only. A different molecule is
    never folded in because it shares a stem, and no synonym or salt expansion is
    attempted — that would be a chemistry claim this pipeline does not make.
    """
    if not query_words:
        return False
    haystack = " ".join(_words(name))
    needle = " ".join(query_words)
    return f" {needle} " in f" {haystack} "


def _is_combination_name(name: str) -> bool:
    return bool(_COMBINATION.search(name or ""))


def _comparator_role(intervention: TrialIntervention) -> bool:
    return bool(intervention.role) and intervention.role.upper() in COMPARATOR_ROLES


def _classify(
    trial: ClinicalTrial,
    query_words: list[str],
    companions: dict[str, str],
) -> tuple[str, list[str], list[str], str]:
    """Return (category, matched intervention names, roles, basis) for one trial.

    `companions` maps a normalised intervention name to the evidence that the
    registry registers it in the same study as the queried product. Naming a
    companion is the only route to the class-related category: no drug-class
    table, no synonym list and no model judgement is consulted.
    """
    matched: list[str] = []
    roles: list[str] = []
    administered = False

    for intervention in trial.intervention_details:
        if not names_query(intervention.name, query_words):
            continue
        matched.append(intervention.name)
        if intervention.role:
            roles.append(intervention.role)
        # A placebo arm is often labelled with the product it masks, so the name
        # alone cannot say which role this record gives the queried product. Only
        # an intervention the registry does NOT type as a comparator, and does not
        # fold into a combination name, is one the study administers as itself.
        if not _comparator_role(intervention) and not _is_combination_name(intervention.name):
            administered = True

    if matched:
        category = DIRECT if administered else COMPARATOR_OR_COMBINATION
        return category, matched, sorted(set(roles)), CATEGORY_BASIS[category]

    registered = {normalize_name(d.name) for d in trial.intervention_details}
    shared = sorted(registered & set(companions))
    if shared:
        return (
            RELATED_NOT_NAMED,
            [],
            [],
            "; ".join(companions[name] for name in shared[:4]),
        )

    wording = " ".join(
        [trial.title or "", *trial.conditions, trial.brief_summary or ""]
    )
    if names_query(wording, query_words):
        return (
            RELATED_NOT_NAMED,
            [],
            [],
            CATEGORY_BASIS[RELATED_NOT_NAMED],
        )
    return NOT_DEMONSTRABLY_RELEVANT, [], [], CATEGORY_BASIS[
        NOT_DEMONSTRABLY_RELEVANT
    ]


def _comparator_trial_ids(trials: Iterable[ClinicalTrial]) -> set[str]:
    """Trials that register a placebo or sham arm — role stated by the registry."""
    return {
        trial.nct_id
        for trial in trials
        if any(
            (intervention.role or "").upper() in MASKED_ROLES
            for intervention in trial.intervention_details
        )
        or any(
            (group.type or "").upper() in MASKED_ROLES
            for group in trial.arm_groups
        )
    }


def _distinct(trials: list[ClinicalTrial]) -> list[ClinicalTrial]:
    """One record per NCT ID, keeping the first spelling seen.

    The same study can arrive twice when a search runs more than one query, and a
    duplicate would add a second row to a category total while the registry still
    calls it one study.
    """
    seen: dict[str, ClinicalTrial] = {}
    for trial in trials:
        if trial.nct_id:
            seen.setdefault(trial.nct_id, trial)
    return list(seen.values())


def attribute_trials(
    trials: list[ClinicalTrial], query: str, applicable: bool = True
) -> QueryAttributionSummary:
    """Sort every retrieved trial by how the registry links it to the query."""
    trials = _distinct(trials)
    query_words = _words(query)
    summary = QueryAttributionSummary(
        query=query,
        applicable=applicable,
        distinct_trials=len(trials),
        rule=(
            "Categories are assigned from the registry's own intervention fields. "
            "Only the first two name the queried product as a registered "
            "intervention, and only those two are counted as studies of it. A "
            "title, condition or indication match alone never makes a trial a "
            "study of the product, and a class relationship is never asserted."
        ),
    )
    if not applicable:
        summary.reason = (
            "This search mode does not name a product, so trial attribution to a "
            "product is not applicable."
        )
        return summary

    comparator_trials = _comparator_trial_ids(trials)
    intervention_names: set[str] = set()
    placebo_or_sham_names: set[str] = set()
    investigational_names: set[str] = set()

    # Pass 1 — the products the registry registers in the same study as the
    # queried one. This is the only class-relationship evidence taken as fact.
    companions: dict[str, list[str]] = {}
    spellings: dict[str, str] = {}
    for trial in trials:
        if not any(
            names_query(d.name, query_words) for d in trial.intervention_details
        ):
            continue
        for detail in trial.intervention_details:
            if names_query(detail.name, query_words) or _comparator_role(detail):
                continue
            name = normalize_name(detail.name)
            if not name:
                continue
            spellings.setdefault(name, detail.name.strip())
            if trial.nct_id not in companions.setdefault(name, []):
                companions[name].append(trial.nct_id)
    companion_evidence = {
        name: f"the registry registers {spellings[name]} with the queried product in "
        + ", ".join(ids)
        for name, ids in companions.items()
    }

    for trial in trials:
        category, matched, roles, basis = _classify(
            trial, query_words, companion_evidence
        )
        if category == DIRECT:
            summary.direct_trials += 1
        elif category == COMPARATOR_OR_COMBINATION:
            summary.comparator_or_combination_trials += 1

        for detail in trial.intervention_details:
            name = normalize_name(detail.name)
            if not name:
                continue
            intervention_names.add(name)
            drug_like = (detail.type or "").upper() in DRUG_LIKE_TYPES
            comparator = (detail.role or "").upper() in MASKED_ROLES
            if comparator:
                placebo_or_sham_names.add(name)
            elif drug_like and not _is_combination_name(detail.name):
                investigational_names.add(name)

        summary.records.append(
            QueryAttribution(
                nct_id=trial.nct_id,
                title=trial.title,
                category=category,
                category_label=CATEGORY_LABELS[category],
                basis=basis,
                matched_interventions=matched,
                registry_roles=roles,
                source_url=trial.source_url or trial.url,
            )
        )
        if category in (RELATED_NOT_NAMED, NOT_DEMONSTRABLY_RELEVANT):
            summary.excluded_nct_ids.append(trial.nct_id)

    summary.query_specific_trials = summary.direct_trials + (
        summary.comparator_or_combination_trials
    )
    summary.related_not_named_trials = sum(
        1 for r in summary.records if r.category == RELATED_NOT_NAMED
    )
    summary.not_demonstrably_relevant_trials = sum(
        1 for r in summary.records if r.category == NOT_DEMONSTRABLY_RELEVANT
    )
    summary.distinct_intervention_names = len(intervention_names)
    summary.placebo_or_sham_arms = len(comparator_trials)
    summary.distinct_investigational_candidates = len(investigational_names)
    summary.placebo_or_sham_names = sorted(placebo_or_sham_names)[:40]
    summary.reconciliation_note = (
        f"{summary.query_specific_trials} + {summary.related_not_named_trials} + "
        f"{summary.not_demonstrably_relevant_trials} = {summary.distinct_trials} "
        "distinct trials; each record is in exactly one category."
    )
    summary.categories = [
        AttributionCategory(
            key=key,
            label=CATEGORY_LABELS[key],
            basis=CATEGORY_BASIS[key],
            count=sum(1 for r in summary.records if r.category == key),
        )
        for key in (
            DIRECT,
            COMPARATOR_OR_COMBINATION,
            RELATED_NOT_NAMED,
            NOT_DEMONSTRABLY_RELEVANT,
        )
    ]
    return summary
