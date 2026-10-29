"""Clinical trial taxonomy, retrieval metadata, and dashboard analytics tests.

All registry payloads here are constructed by the test and served through respx,
so nothing in this file touches ClinicalTrials.gov.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from integrations.clinicaltrials import fetch_trials
from models.schemas import ClinicalTrial, TrialRetrievalMetadata
from services import trial_taxonomy
from services.trial_analytics import compute_analytics

CT_STUDIES_URL = "https://clinicaltrials.gov/api/v2/studies"


# ---------------------------------------------------------------------------
# Status taxonomy
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "code,category",
    [
        ("RECRUITING", "currently_recruiting"),
        ("ENROLLING_BY_INVITATION", "currently_recruiting"),
        ("ACTIVE_NOT_RECRUITING", "ongoing_not_recruiting"),
        ("NOT_YET_RECRUITING", "not_yet_started"),
        ("SUSPENDED", "paused"),
        ("COMPLETED", "completed"),
        ("TERMINATED", "discontinued"),
        ("WITHDRAWN", "discontinued"),
        ("UNKNOWN", "other_or_unclear"),
    ],
)
def test_status_categories_match_the_documented_rules(code, category):
    assert trial_taxonomy.status_category(code) == category


def test_unrecognised_status_is_kept_and_reported_as_other():
    """A status the registry invents later must not be dropped or re-bucketed."""
    assert trial_taxonomy.status_category("SOMETHING_NEW") == "other_or_unclear"
    assert trial_taxonomy.status_label("SOMETHING_NEW") == "Something New"


def test_status_category_accepts_human_labels_too():
    assert trial_taxonomy.status_category("Active, not recruiting") == "ongoing_not_recruiting"


def test_ongoing_excludes_not_yet_recruiting_and_paused():
    assert trial_taxonomy.is_ongoing("RECRUITING")
    assert trial_taxonomy.is_ongoing("ACTIVE_NOT_RECRUITING")
    assert not trial_taxonomy.is_ongoing("NOT_YET_RECRUITING")
    assert not trial_taxonomy.is_ongoing("SUSPENDED")
    assert not trial_taxonomy.is_ongoing("COMPLETED")
    assert not trial_taxonomy.is_ongoing(None)


# ---------------------------------------------------------------------------
# Phase taxonomy
# ---------------------------------------------------------------------------


def test_combined_phase_is_not_collapsed_into_one_bucket():
    assert trial_taxonomy.normalize_phase("PHASE1/PHASE2") == "Phase 1/2"
    assert trial_taxonomy.phase_category(["PHASE1", "PHASE2"]) == "Phase 1 + Phase 2"


def test_missing_phase_stays_unknown_rather_than_being_invented():
    assert trial_taxonomy.phase_category([]) == trial_taxonomy.UNKNOWN_PHASE
    assert trial_taxonomy.phase_category(["", None]) == trial_taxonomy.UNKNOWN_PHASE
    assert not trial_taxonomy.has_known_phase([])


def test_phase_sort_puts_unknown_last():
    ordered = sorted(
        [trial_taxonomy.UNKNOWN_PHASE, "Phase 1", "Phase 3"],
        key=trial_taxonomy.phase_sort_key,
    )
    assert ordered == ["Phase 1", "Phase 3", trial_taxonomy.UNKNOWN_PHASE]


# ---------------------------------------------------------------------------
# fetch_trials: provenance and honesty
# ---------------------------------------------------------------------------


def _study(nct_id, status="RECRUITING", phases=("PHASE2",), start=None):
    status_module = {"overallStatus": status}
    if start:
        status_module["startDateStruct"] = {"date": start, "type": "ACTUAL"}
    return {
        "protocolSection": {
            "identificationModule": {"nctId": nct_id, "briefTitle": f"Study {nct_id}"},
            "statusModule": status_module,
            "designModule": {"studyType": "INTERVENTIONAL", "phases": list(phases)},
            "conditionsModule": {"conditions": ["Alzheimer Disease"]},
        }
    }


@pytest.mark.asyncio
@respx.mock
async def test_fetch_trials_returns_records_and_metadata():
    respx.get(CT_STUDIES_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "studies": [_study("NCT00000001", start="2003-01")],
                "nextPageToken": "token-2",
            },
        )
    )

    trials, metadata = await fetch_trials("Alzheimer")

    assert len(trials) == 1
    assert trials[0].overall_status == "RECRUITING"
    assert trials[0].status_category == "currently_recruiting"
    assert trials[0].ongoing is True
    # Partial registry dates are preserved, not padded to a fabricated day.
    assert trials[0].start_date == "2003-01"
    assert metadata.records_returned == 1
    assert metadata.has_more is True
    assert metadata.partial is True
    assert "not the complete universe" in metadata.note


@pytest.mark.asyncio
@respx.mock
async def test_fetch_trials_deduplicates_by_nct_id():
    respx.get(CT_STUDIES_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "studies": [_study("NCT00000001"), _study("NCT00000001")],
            },
        )
    )

    trials, metadata = await fetch_trials("Alzheimer")

    assert len(trials) == 1
    assert metadata.records_returned == 1
    assert metadata.has_more is False


@pytest.mark.asyncio
@respx.mock
async def test_fetch_trials_reports_empty_without_denying_trials_exist():
    respx.get(CT_STUDIES_URL).mock(return_value=httpx.Response(200, json={"studies": []}))

    trials, metadata = await fetch_trials("Obscure")

    assert trials == []
    assert "does not establish" in metadata.note


@pytest.mark.asyncio
@respx.mock
async def test_fetch_trials_distinguishes_api_failure_from_no_results():
    respx.get(CT_STUDIES_URL).mock(return_value=httpx.Response(503))

    trials, metadata = await fetch_trials("Alzheimer")

    assert trials == []
    assert metadata.partial is True
    assert "could not be reached" in metadata.note


# ---------------------------------------------------------------------------
# compute_analytics
# ---------------------------------------------------------------------------


def _trial(nct_id, status, phases, start=None):
    return ClinicalTrial(
        nct_id=nct_id,
        overall_status=status,
        status_category=trial_taxonomy.status_category(status),
        phases=phases,
        phase_category=trial_taxonomy.phase_category(phases),
        ongoing=trial_taxonomy.is_ongoing(status),
        start_date=start,
    )


def _metadata():
    return TrialRetrievalMetadata(query="q", retrieved_at="2026-10-12T00:00:00+00:00")


def test_analytics_counts_come_from_one_deduplicated_set():
    records = [
        _trial("NCT1", "RECRUITING", ["PHASE2"], "2021-03"),
        _trial("NCT1", "RECRUITING", ["PHASE2"], "2021-03"),
        _trial("NCT2", "ACTIVE_NOT_RECRUITING", ["PHASE3"], "2019-06"),
        _trial("NCT3", "NOT_YET_RECRUITING", ["PHASE1"], "2026-01"),
        _trial("NCT4", "COMPLETED", [], "2015-02"),
        _trial("NCT5", "TERMINATED", ["PHASE2"], None),
        _trial("NCT6", "SUSPENDED", ["PHASE1/PHASE2"], "2018-09"),
        _trial("NCT7", "UNKNOWN", ["PHASE4"], "2020-11"),
    ]

    a = compute_analytics(records, _metadata())

    assert a.total_trials == 7
    # Ongoing = recruiting + enrolling by invitation + active, not recruiting.
    assert a.ongoing_trials == 2
    assert a.recruiting_trials == 1
    assert a.not_yet_recruiting_trials == 1
    assert a.completed_trials == 1
    assert a.discontinued_trials == 1
    assert a.paused_trials == 1
    assert a.other_status_trials == 1
    assert a.trials_with_unreported_phase == 1


def test_status_category_counts_do_not_double_count():
    a = compute_analytics(
        [
            _trial("NCT1", "RECRUITING", ["PHASE2"]),
            _trial("NCT2", "ENROLLING_BY_INVITATION", ["PHASE2"]),
            _trial("NCT3", "COMPLETED", ["PHASE3"]),
        ],
        _metadata(),
    )

    assert sum(b.count for b in a.trials_by_status) == a.total_trials


def test_status_cards_partition_the_record_set_exactly_once():
    """The mutually exclusive status cards must sum to the total, and Ongoing
    must be the documented union of recruiting and active-not-recruiting."""
    a = compute_analytics(
        [
            _trial("NCT1", "RECRUITING", ["PHASE2"]),
            _trial("NCT2", "ENROLLING_BY_INVITATION", ["PHASE2"]),
            _trial("NCT3", "ACTIVE_NOT_RECRUITING", ["PHASE3"]),
            _trial("NCT4", "NOT_YET_RECRUITING", ["PHASE1"]),
            _trial("NCT5", "SUSPENDED", ["PHASE1"]),
            _trial("NCT6", "COMPLETED", ["PHASE4"]),
            _trial("NCT7", "TERMINATED", ["PHASE2"]),
            _trial("NCT8", "WITHDRAWN", ["PHASE2"]),
            _trial("NCT9", "AVAILABLE", ["PHASE3"]),
            _trial("NCT10", "UNKNOWN", ["PHASE3"]),
        ],
        _metadata(),
    )

    exclusive = (
        a.currently_recruiting_trials
        + a.active_not_recruiting_trials
        + a.not_yet_recruiting_trials
        + a.completed_trials
        + a.discontinued_trials
        + a.paused_trials
        + a.other_status_trials
    )
    assert exclusive == a.total_trials == 10
    assert a.ongoing_trials == a.currently_recruiting_trials + a.active_not_recruiting_trials == 3


def test_recruiting_card_is_strictly_the_recruiting_status():
    """"Enrolling by invitation" is its own registry status, not a recruiting count.

    The dashboard category that groups the two is reported separately, so a reader
    who wants the registry's own word and one who wants the group both get a
    number that says which it is.
    """
    a = compute_analytics(
        [
            _trial("NCT1", "RECRUITING", ["PHASE2"]),
            _trial("NCT2", "ENROLLING_BY_INVITATION", ["PHASE2"]),
        ],
        _metadata(),
    )

    assert a.recruiting_trials == 1
    assert a.enrolling_by_invitation_trials == 1
    assert a.currently_recruiting_trials == 2
    # Ongoing is a re-cut of the same records, never a fourth bucket to add.
    assert a.ongoing_trials == 2
    assert a.statuses_reconcile is True


def test_status_groups_carry_the_membership_that_produced_their_count():
    """A heading and its arithmetic travel together, so they cannot drift apart."""
    a = compute_analytics(
        [
            _trial("NCT1", "RECRUITING", ["PHASE2"]),
            _trial("NCT2", "ENROLLING_BY_INVITATION", ["PHASE2"]),
            _trial("NCT3", "COMPLETED", ["PHASE3"]),
        ],
        _metadata(),
    )

    recruiting = next(g for g in a.status_groups if g.category == "currently_recruiting")
    assert recruiting.count == 2
    assert recruiting.registry_statuses == ["Recruiting", "Enrolling by invitation"]
    assert "Recruiting" in recruiting.definition and "Enrolling by invitation" in recruiting.definition
    assert sum(g.count for g in a.status_groups if g.category != "ongoing") == a.total_trials


def test_ongoing_chart_only_contains_ongoing_studies():
    records = [
        _trial("NCT1", "RECRUITING", ["PHASE2"]),
        _trial("NCT2", "NOT_YET_RECRUITING", ["PHASE2"]),
        _trial("NCT3", "SUSPENDED", ["PHASE3"]),
    ]

    a = compute_analytics(records, _metadata())

    assert [b.label for b in a.ongoing_trials_by_phase] == ["Phase 2"]
    assert a.ongoing_trials_by_phase[0].count == 1


def test_phases_are_ordered_by_clinical_progression():
    records = [
        _trial("NCT1", "COMPLETED", ["PHASE4"]),
        _trial("NCT2", "COMPLETED", ["PHASE1"]),
        _trial("NCT3", "COMPLETED", []),
        _trial("NCT4", "COMPLETED", ["PHASE3"]),
    ]

    a = compute_analytics(records, _metadata())

    assert [b.label for b in a.trials_by_phase] == [
        "Phase 1",
        "Phase 3",
        "Phase 4",
        trial_taxonomy.UNKNOWN_PHASE,
    ]


def test_timeline_is_omitted_when_too_few_dates_exist():
    a = compute_analytics(
        [
            _trial("NCT1", "COMPLETED", ["PHASE2"], "2020-01"),
            _trial("NCT2", "COMPLETED", ["PHASE2"], None),
            _trial("NCT3", "COMPLETED", ["PHASE2"], "not-a-date"),
        ],
        _metadata(),
    )

    assert a.trial_starts_by_period == []
    assert a.timeline_omitted_reason
    assert a.excluded_from_timeline_count == 2


def test_unusable_dates_are_excluded_from_the_timeline_not_repaired():
    """An out-of-range month is a bad date, not a day to guess at."""
    a = compute_analytics(
        [
            _trial("NCT1", "COMPLETED", ["PHASE2"], "2020-13"),
            _trial("NCT2", "COMPLETED", ["PHASE2"], "2020-07"),
            _trial("NCT3", "COMPLETED", ["PHASE2"], "2021-02"),
            _trial("NCT4", "COMPLETED", ["PHASE2"], "2021-09"),
        ],
        _metadata(),
    )

    assert a.excluded_from_timeline_count == 1
    # The rejected record leaves no trace in the buckets, only in the count.
    assert a.timeline_granularity == "month"
    assert [(p.period, p.count) for p in a.trial_starts_by_period] == [
        ("2020-07", 1),
        ("2021-02", 1),
        ("2021-09", 1),
    ]


def test_long_span_bundles_the_timeline_by_year():
    records = [
        _trial("NCT1", "COMPLETED", ["PHASE2"], "2005-03"),
        _trial("NCT2", "COMPLETED", ["PHASE2"], "2005-11"),
        _trial("NCT3", "COMPLETED", ["PHASE2"], "2019-04"),
    ]

    a = compute_analytics(records, _metadata())

    assert a.timeline_granularity == "year"
    assert [(p.period, p.count) for p in a.trial_starts_by_period] == [
        ("2005", 2),
        ("2019", 1),
    ]


def test_short_span_with_full_dates_bundles_by_month():
    records = [
        _trial("NCT1", "COMPLETED", ["PHASE2"], "2024-03-11"),
        _trial("NCT2", "COMPLETED", ["PHASE2"], "2024-03-27"),
        _trial("NCT3", "COMPLETED", ["PHASE2"], "2024-08-02"),
    ]

    a = compute_analytics(records, _metadata())

    assert a.timeline_granularity == "month"
    assert [(p.period, p.count) for p in a.trial_starts_by_period] == [
        ("2024-03", 2),
        ("2024-08", 1),
    ]


def test_empty_input_yields_zeroed_analytics_not_fabricated_buckets():
    a = compute_analytics([], _metadata())

    assert a.total_trials == 0
    assert a.trials_by_phase == []
    assert a.trials_by_status == []
    assert a.ongoing_trials == 0
