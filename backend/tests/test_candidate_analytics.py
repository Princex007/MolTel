"""Candidate-level analytics (spec §4.4, §5.1).

Everything here is computed from registry records the test supplies, so the
assertions are about counting rules, not about a live API.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from integrations.clinicaltrials import fetch_trials
from models.schemas import (
    ClinicalTrial,
    EvidenceItem,
    TrialIntervention,
    TrialRetrievalMetadata,
)
from services.candidate_analytics import DRUG_LIKE_TYPES, compute_candidates, normalize_name

CT_STUDIES_URL = "https://clinicaltrials.gov/api/v2/studies"


def _trial(nct_id, interventions, status="RECRUITING", phases=("PHASE2",), sponsor="Academic Center"):
    trial = ClinicalTrial(
        nct_id=nct_id,
        title=f"Study {nct_id}",
        status=status.replace("_", " ").title(),
        phase=", ".join(phases),
        conditions=["Type 2 Diabetes"],
        interventions=[i.name for i in interventions],
        intervention_details=interventions,
        sponsor=sponsor,
        overall_status=status,
        phases=list(phases),
        ongoing=status in {"RECRUITING", "ACTIVE_NOT_RECRUITING", "ENROLLING_BY_INVITATION"},
        start_date="2019-01",
        completion_date="2021-01",
        last_update_date="2024-05-01",
        source_url=f"https://clinicaltrials.gov/study/{nct_id}",
        retrieved_at="2026-10-23T00:00:00Z",
    )
    return trial


def _metadata():
    return TrialRetrievalMetadata(query="diabetes", retrieved_at="2026-10-23T00:00:00Z", records_returned=3)


def test_a_candidate_is_distinct_from_a_trial():
    """Two trials naming one product are one candidate, not two."""
    analytics = compute_candidates(
        [
            _trial("NCT00000001", [TrialIntervention(name="Semaglutide", type="DRUG")]),
            _trial("NCT00000002", [TrialIntervention(name="semaglutide", type="Drug")]),
        ],
        _metadata(),
    )
    assert analytics.distinct_candidates == 1
    assert analytics.candidate_trials_considered == 2
    assert analytics.records[0].trials == 2
    assert analytics.records[0].name in {"Semaglutide", "semaglutide"}


def test_a_trial_may_study_more_than_one_candidate():
    analytics = compute_candidates(
        [
            _trial(
                "NCT00000003",
                [
                    TrialIntervention(name="Metformin", type="DRUG"),
                    TrialIntervention(name="Empagliflozin", type="DRUG"),
                ],
            )
        ],
        _metadata(),
    )
    assert analytics.distinct_candidates == 2
    assert all(r.trials == 1 for r in analytics.records)


def test_formulations_are_not_merged_into_one_candidate():
    """Conservative matching: 'Aspirin' and 'Aspirin, buffered' stay separate."""
    analytics = compute_candidates(
        [
            _trial("NCT00000004", [TrialIntervention(name="Aspirin", type="DRUG")]),
            _trial(
                "NCT00000005",
                [TrialIntervention(name="Aspirin, buffered", type="DRUG")],
            ),
        ],
        _metadata(),
    )
    assert analytics.distinct_candidates == 2


def test_non_drug_interventions_are_reported_not_counted_as_candidates():
    analytics = compute_candidates(
        [
            _trial(
                "NCT00000006",
                [TrialIntervention(name="Cognitive training", type="BEHAVIORAL")],
            )
        ],
        _metadata(),
    )
    assert analytics.distinct_candidates == 0
    assert analytics.trials_without_named_intervention == 1
    assert [b.label for b in analytics.non_drug_intervention_types] == ["Behavioral"]
    assert analytics.non_drug_intervention_types[0].count == 1


def test_an_intervention_without_a_registry_type_is_not_assumed_to_be_a_drug():
    analytics = compute_candidates(
        [_trial("NCT00000007", [TrialIntervention(name="Something", type=None)])],
        _metadata(),
    )
    assert analytics.distinct_candidates == 0
    assert analytics.non_drug_intervention_types[0].label == "No type reported by the registry"


def test_a_placebo_comparator_stays_counted_and_is_named():
    """The registry types Placebo as a DRUG, so it is a candidate name here.

    It is reported rather than dropped — silently removing it would change what
    the source states — but counted separately so the list is not read as a
    development pipeline.
    """
    analytics = compute_candidates(
        [
            _trial(
                "NCT00000020",
                [
                    TrialIntervention(name="Placebo", type="DRUG"),
                    TrialIntervention(name="Metformin", type="DRUG"),
                ],
            )
        ],
        _metadata(),
    )
    assert analytics.distinct_candidates == 2
    assert analytics.comparator_candidates == 1
    assert [r.name for r in analytics.records] == ["Metformin", "Placebo"]
    assert "named comparator such as placebo" in analytics.counting_rule


def test_a_product_that_is_not_a_comparator_is_not_labelled_one():
    """A combination arm that contains a placebo is still a product name."""
    analytics = compute_candidates(
        [
            _trial(
                "NCT00000021",
                [
                    TrialIntervention(name="Insulin glargine", type="DRUG"),
                    TrialIntervention(name="placebo+metformin", type="DRUG"),
                ],
            )
        ],
        _metadata(),
    )
    assert analytics.comparator_candidates == 0


def test_sponsorship_is_never_reported_as_development():
    analytics = compute_candidates(
        [_trial("NCT00000008", [TrialIntervention(name="Drug X", type="DRUG")], sponsor="Pharma Co")],
        _metadata(),
    )
    record = analytics.records[0]
    assert record.sponsors == ["Pharma Co"]
    assert record.developer is None
    assert record.developer_note == "Developer not established"
    assert record.label_manufacturer is None
    assert analytics.candidates_with_established_developer == 0


def test_a_label_manufacturer_is_recorded_separately_from_a_developer():
    label = EvidenceItem(
        source="openFDA",
        source_type="regulatory",
        title="Drug X — Indications",
        url="https://api.fda.gov/drug/label.json?limit=1&search=application_number:%22NDA0001%22",
        metadata={
            "label_manufacturer": "Packager Ltd",
            "generic_names": ["drug x"],
            "brand_names": ["XBrand"],
            "application_number": "NDA0001",
        },
    )
    analytics = compute_candidates(
        [_trial("NCT00000009", [TrialIntervention(name="Drug X", type="DRUG")], sponsor="University")],
        _metadata(),
        [label],
    )
    record = analytics.records[0]
    assert record.label_manufacturer == "Packager Ltd"
    assert record.fda_application_number == "NDA0001"
    # The label names neither a holder nor a developer, and the record says so.
    assert record.developer is None
    assert record.developer_note == "Developer not established"
    assert "neither is treated as the developer" in record.label_note
    assert analytics.candidates_with_openfda_label == 1
    # Both companies appear, each with the claim that puts it there.
    attributions = {row.company: row.attribution for row in analytics.company_by_phase}
    assert attributions == {
        "Packager Ltd": "Manufacturer named on an openFDA label",
        "University": "Lead sponsor of a trial studying this product",
    }


def test_a_company_named_by_two_sources_is_counted_once_per_candidate():
    label = EvidenceItem(
        source="openFDA",
        source_type="regulatory",
        metadata={
            "label_manufacturer": "Pharma Co",
            "generic_names": ["drug y"],
            "application_number": "NDA0002",
        },
    )
    analytics = compute_candidates(
        [_trial("NCT00000010", [TrialIntervention(name="Drug Y", type="DRUG")], sponsor="Pharma Co")],
        _metadata(),
        [label],
    )
    assert [b.count for b in analytics.candidates_by_company] == [1]
    assert analytics.company_by_phase[0].attribution == (
        "Manufacturer named on an openFDA label; "
        "Lead sponsor of a trial studying this product"
    )


def test_distinct_candidate_phase_counts_use_one_bucket_per_candidate():
    """A candidate in two phases is counted once per phase, and the rule says so."""
    analytics = compute_candidates(
        [
            _trial("NCT00000010", [TrialIntervention(name="Duple", type="DRUG")], phases=("PHASE1",)),
            _trial("NCT00000011", [TrialIntervention(name="Duple", type="DRUG")], phases=("PHASE3",)),
        ],
        _metadata(),
    )
    assert analytics.distinct_candidates == 1
    assert {b.label: b.count for b in analytics.candidates_by_phase} == {
        "Phase 1": 1,
        "Phase 3": 1,
    }
    assert "sum above the number of distinct candidates" in analytics.counting_rule


def test_combined_phase_stays_one_category_for_a_candidate():
    analytics = compute_candidates(
        [
            _trial(
                "NCT00000012",
                [TrialIntervention(name="Combined", type="DRUG")],
                phases=("PHASE1/PHASE2",),
            )
        ],
        _metadata(),
    )
    assert [b.label for b in analytics.candidates_by_phase] == ["Phase 1/2"]
    assert analytics.records[0].highest_phase == "Phase 1/2"


def test_unknown_and_not_applicable_phases_are_separate_from_real_phases():
    analytics = compute_candidates(
        [
            _trial("NCT00000013", [TrialIntervention(name="NoPhase", type="DRUG")], phases=()),
            _trial(
                "NCT00000014",
                [TrialIntervention(name="NoPhase", type="DRUG")],
                phases=("NA",),
            ),
        ],
        _metadata(),
    )
    labels = [b.label for b in analytics.candidates_by_phase]
    assert "Unknown / Not Reported" in labels
    assert "Not Applicable" in labels
    assert analytics.records[0].highest_phase is None


def test_ongoing_candidate_counts_exclude_completed_only_trials():
    analytics = compute_candidates(
        [
            _trial(
                "NCT00000015",
                [TrialIntervention(name="Live", type="DRUG")],
                status="RECRUITING",
            ),
            _trial(
                "NCT00000016",
                [TrialIntervention(name="Live", type="DRUG")],
                status="COMPLETED",
            ),
            _trial(
                "NCT00000017",
                [TrialIntervention(name="Finished", type="DRUG")],
                status="COMPLETED",
            ),
        ],
        _metadata(),
    )
    assert {b.label: b.count for b in analytics.ongoing_candidates_by_phase} == {"Phase 2": 1}
    assert next(r for r in analytics.records if r.name == "Live").ongoing_trials == 1


def test_provenance_fields_travel_with_the_candidate():
    analytics = compute_candidates(
        [_trial("NCT00000018", [TrialIntervention(name="Traced", type="DRUG")])],
        _metadata(),
    )
    record = analytics.records[0]
    assert record.source_links == ["https://clinicaltrials.gov/study/NCT00000018"]
    assert record.last_update_date == "2024-05-01"
    assert record.retrieved_at == "2026-10-23T00:00:00Z"
    assert record.conditions == ["Type 2 Diabetes"]


def test_normalization_only_touches_case_and_whitespace():
    assert normalize_name("  very   Long  Name ") == "very long name"
    assert normalize_name("Aspirin") != normalize_name("Aspirin effervescent")


def test_drug_like_types_are_an_explicit_list():
    assert "DEVICE" not in DRUG_LIKE_TYPES
    assert {"DRUG", "BIOLOGICAL"} <= DRUG_LIKE_TYPES


def _study_with_arms(nct_id, interventions, collaborators=None):
    return {
        "protocolSection": {
            "identificationModule": {"nctId": nct_id, "briefTitle": f"Study {nct_id}"},
            "statusModule": {"overallStatus": "RECRUITING"},
            "designModule": {"studyType": "INTERVENTIONAL", "phases": ["PHASE2"]},
            "conditionsModule": {"conditions": ["Asthma"]},
            "armsInterventionsModule": {"interventions": interventions},
            "sponsorCollaboratorsModule": {
                "leadSponsor": {"name": "Aero Institute"},
                "collaborators": collaborators or [],
            },
        }
    }


@pytest.mark.asyncio
@respx.mock
async def test_registry_intervention_types_and_collaborators_are_preserved():
    respx.get(CT_STUDIES_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "studies": [
                    _study_with_arms(
                        "NCT00000020",
                        [
                            {"name": " Fluticasone ", "type": "DRUG"},
                            {"name": "Nebuliser", "type": "DEVICE"},
                        ],
                        [{"name": "Air Health Ltd", "class": "INDUSTRY"}],
                    )
                ]
            },
        )
    )

    trials, _ = await fetch_trials("asthma")
    trial = trials[0]
    assert [i.name for i in trial.intervention_details] == ["Fluticasone", "Nebuliser"]
    assert [i.type for i in trial.intervention_details] == ["DRUG", "DEVICE"]
    assert trial.collaborators[0].name == "Air Health Ltd"
    assert trial.collaborators[0].registry_class == "INDUSTRY"

    analytics = compute_candidates(trials, _)
    assert analytics.distinct_candidates == 1
    assert [b.label for b in analytics.non_drug_intervention_types] == ["Device"]
