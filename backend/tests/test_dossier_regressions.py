"""Regression tests for the defects found in the semaglutide dossier.

Each test here is one of the fifteen failure cases listed in §10 of the dossier
fix brief. Every record under test is a fixture captured from the authoritative
source (ClinicalTrials.gov v2) on 2026-10-29, so nothing in this file reaches the
network, calls the model or spends AI credits.

The tests assert on pipeline behaviour — what the gate reports, not what a PDF
once said. A correction that only fixes semaglutide would be a fixture, and the
brief forbids that: nothing below special-cases a molecule.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from integrations.clinicaltrials import _parse_study
from models.schemas import (
    ClinicalTrial,
    Contradiction,
    ContradictoryFindings,
    Dossier,
    EvidenceItem,
    EvidenceType,
    ResearchGap,
    SourceStatus,
    TrialArmGroup,
    TrialIntervention,
    TrialRetrievalMetadata,
    ValidationReport,
)
from services.candidate_analytics import compute_candidates
from services.dossier_generator import DossierGenerator
from services.dossier_validator import (
    RULES,
    _NARRATIVE_FIELDS,
    collect_identifiers,
    collect_label_products,
    validate_dossier,
)
from services.evidence_normalizer import deduplicate
from services.evidence_strength import compute_evidence_strength
from services.trial_analytics import compute_analytics
from services.trial_attribution import (
    COMPARATOR_OR_COMBINATION,
    DIRECT,
    NOT_DEMONSTRABLY_RELEVANT,
    RELATED_NOT_NAMED,
    attribute_trials,
)

QUERY = "semaglutide"
RETRIEVED_AT = "2026-10-29T00:00:00+00:00"
FIXTURES = Path(__file__).parent / "fixtures"

NCT_ALZHEIMER = "NCT04777409"  # COMPLETED, PHASE3, oral semaglutide vs placebo
NCT_PK = "NCT05671653"  # TERMINATED, PHASE1, two cohorts of study drugs
NCT_PSORIASIS = "NCT07401992"  # RECRUITING, PHASE4, semaglutide as comparator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fixture(nct_id: str) -> ClinicalTrial:
    """Replay a registry record captured from ClinicalTrials.gov v2."""
    study = json.loads((FIXTURES / f"{nct_id}.json").read_text(encoding="utf-8"))
    trial = _parse_study(study, RETRIEVED_AT)
    assert trial is not None and trial.nct_id == nct_id
    return trial


@pytest.fixture(scope="module")
def alzheimer_trial() -> ClinicalTrial:
    return _fixture(NCT_ALZHEIMER)


@pytest.fixture(scope="module")
def pk_trial() -> ClinicalTrial:
    return _fixture(NCT_PK)


@pytest.fixture(scope="module")
def psoriasis_trial() -> ClinicalTrial:
    return _fixture(NCT_PSORIASIS)


@pytest.fixture(scope="module")
def semaglutide_trials(
    alzheimer_trial: ClinicalTrial,
    pk_trial: ClinicalTrial,
    psoriasis_trial: ClinicalTrial,
) -> list[ClinicalTrial]:
    return [alzheimer_trial, pk_trial, psoriasis_trial]


def _metadata(count: int = 0, **kwargs) -> TrialRetrievalMetadata:
    return TrialRetrievalMetadata(
        query=QUERY,
        retrieved_at=RETRIEVED_AT,
        records_returned=count,
        **kwargs,
    )


def _intervention(
    name: str, type_: str = "DRUG", role: str | None = None, arms: list[str] = ()
) -> TrialIntervention:
    return TrialIntervention(
        name=name, type=type_, role=role, arm_group_labels=list(arms)
    )


def _arm(label: str, type_: str, names: list[str]) -> TrialArmGroup:
    return TrialArmGroup(label=label, type=type_, intervention_names=names)


def _trial(
    nct_id: str,
    *,
    title: str = "",
    status: str = "COMPLETED",
    phase: str = "Phase 3",
    interventions: list[TrialIntervention] = (),
    arms: list[TrialArmGroup] = (),
    conditions: list[str] = (),
    enrollment: int | None = None,
    start_date: str | None = "2021-01-01",
    completion_date: str | None = "2022-01-01",
    time_frames: list[str] = (),
) -> ClinicalTrial:
    """A registry-shaped record for a case no captured fixture happens to contain."""
    return ClinicalTrial(
        nct_id=nct_id,
        title=title or f"Study {nct_id}",
        status=status.replace("_", " ").title(),
        phase=phase,
        overall_status=status,
        conditions=list(conditions),
        interventions=[i.name for i in interventions],
        intervention_details=list(interventions),
        arm_groups=list(arms),
        enrollment_count=enrollment,
        start_date=start_date,
        completion_date=completion_date,
        outcome_time_frames=list(time_frames),
        source_url=f"https://clinicaltrials.gov/study/{nct_id}",
        retrieved_at=RETRIEVED_AT,
    )


def _publication(index: int, evidence_type: EvidenceType) -> EvidenceItem:
    pmid = str(10000000 + index)
    return EvidenceItem(
        source="PubMed",
        source_type="literature",
        id=pmid,
        title=f"Record {index}",
        url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
        evidence_type=evidence_type,
        metadata={"pmid": pmid},
    )


def _label_passage(index: int) -> EvidenceItem:
    return EvidenceItem(
        source="openFDA",
        source_type="regulatory",
        id=f"NDA21305{index}",
        title=f"Label section {index}",
        abstract="AWarnings and precautions text.",
        url="https://api.fda.gov/drug/label.json",
        evidence_type=EvidenceType.regulatory,
        metadata={
            "section": f"warnings_{index}",
            "section_title": "Warnings And Precautions",
            "generic_names": ["semaglutide"],
            "brand_names": ["ozempic"],
        },
    )


def _report(
    narrative: str,
    trials: list[ClinicalTrial],
    field: str = "clinical_development",
    **kwargs,
) -> ValidationReport:
    """Run the gate over one narrative sentence against these records."""
    dossier = Dossier(query=QUERY, **{field: narrative})
    kwargs.setdefault("identifiers", [t.nct_id for t in trials])
    return validate_dossier(dossier, trials, **kwargs)


def _rules(report: ValidationReport) -> set[str]:
    return {finding.rule for finding in report.findings}


def _matches(report: ValidationReport, rule: str) -> list[str]:
    return [f.quote for f in report.findings if f.rule == rule]


def _severity(report: ValidationReport, rule: str) -> set[str]:
    return {f.severity for f in report.findings if f.rule == rule}


def _payload(trials, evidence=(), **kwargs) -> dict:
    """The JSON the model is handed — the same numbers the tables are built from."""
    generator = DossierGenerator()
    return json.loads(
        generator._build_evidence_payload(
            list(evidence), None, list(trials), [], **kwargs
        )
    )


# ---------------------------------------------------------------------------
# 1 and 2 — phase consistency across source data, narrative, table and chart
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "nct_id,registry_phase,registry_status",
    [
        (NCT_ALZHEIMER, "PHASE3", "COMPLETED"),
        (NCT_PSORIASIS, "PHASE4", "RECRUITING"),
    ],
)
def test_registry_phase_and_status_survive_parsing(
    nct_id, registry_phase, registry_status
):
    """The record keeps the registry's own values; nothing is inferred downstream."""
    trial = _fixture(nct_id)
    assert trial.phases == [registry_phase]
    assert trial.overall_status == registry_status


@pytest.mark.parametrize(
    "nct_id,label,claimed,expected_rule",
    [
        (NCT_ALZHEIMER, "Phase 3", "Phase 2", "TRIAL_PHASE_MISMATCH"),
        (NCT_PSORIASIS, "Phase 4", "Phase 3", "TRIAL_PHASE_MISMATCH"),
    ],
)
def test_phase_agrees_across_source_chart_and_narrative(
    nct_id, label, claimed, expected_rule
):
    trial = _fixture(nct_id)
    assert trial.phase == label

    # The chart the dashboard draws buckets on the same label, one trial per bucket.
    analytics = compute_analytics([trial], _metadata(1))
    phase_rows = {b.label: b.count for b in analytics.trials_by_phase}
    assert phase_rows == {label: 1}

    # The table reads the response field the parser filled from the registry.
    assert trial.model_dump()["phase"] == label

    # A narrative that quotes the registry value passes; one that drifts is an error.
    clean = _report(f"{nct_id} is a {label} study.", [trial], analytics=analytics)
    assert _matches(clean, expected_rule) == []
    assert clean.blocked is False

    drift = _report(
        f"{nct_id} was a {claimed} trial.", [trial], analytics=analytics
    )
    assert _matches(drift, expected_rule)
    assert drift.blocked is True
    finding = next(f for f in drift.findings if f.rule == expected_rule)
    assert finding.severity == "error"
    assert finding.status == "fail"
    # The finding names the source value and links to the record it came from.
    assert label in finding.expected
    assert nct_id in finding.source_ref


def test_status_wording_in_the_narrative_is_checked_against_the_registry():
    trial = _fixture(NCT_PSORIASIS)
    wrong = _report(f"{trial.nct_id} has completed enrolment.", [trial])
    assert _rules(wrong) == {"TRIAL_STATUS_MISMATCH"}

    right = _report(f"{trial.nct_id} is recruiting participants.", [trial])
    assert _severity(right, "TRIAL_STATUS_MISMATCH") == set()


def test_a_list_sentence_judges_each_trial_by_its_own_wording():
    """A phase written beside one identifier is not a claim about the next one.

    The narrative lists studies in one sentence; attributing the sentence's first
    phase to every NCT in it would invent errors the record does not contain.
    """
    trials = [_fixture(NCT_ALZHEIMER), _fixture(NCT_PSORIASIS)]
    honest = _report(
        "The Phase 3 early Alzheimer's study is "
        f"{NCT_ALZHEIMER}, and the Phase 4 comparator study is {NCT_PSORIASIS}.",
        trials,
    )
    assert _matches(honest, "TRIAL_PHASE_MISMATCH") == []

    swapped = _report(
        "The Phase 4 early Alzheimer's study is "
        f"{NCT_ALZHEIMER}, and the Phase 3 comparator study is {NCT_PSORIASIS}.",
        trials,
    )
    phase_errors = [
        f for f in swapped.findings if f.rule == "TRIAL_PHASE_MISMATCH"
    ]
    assert len(phase_errors) == 2
    assert all("beside it" in f.observed for f in phase_errors)


def test_a_disjunctive_status_phrase_does_not_contradict_either_state():
    """"Recruiting or active trials include X" is true of both registry states."""
    active = _trial(
        "NCT00000010",
        title="Semaglutide in chronic kidney disease",
        status="ACTIVE_NOT_RECRUITING",
        interventions=[_intervention("Semaglutide", "DRUG", "EXPERIMENTAL", ["A"])],
        arms=[_arm("A", "EXPERIMENTAL", ["Drug: Semaglutide"])],
    )
    report = _report(
        "Currently recruiting or active trials include NCT00000010.", [active]
    )
    assert _matches(report, "TRIAL_STATUS_MISMATCH") == []

    # A record in neither of the two states is still named.
    completed = _trial(
        "NCT00000011",
        title="Semaglutide in chronic kidney disease",
        status="COMPLETED",
        interventions=[_intervention("Semaglutide", "DRUG", "EXPERIMENTAL", ["A"])],
        arms=[_arm("A", "EXPERIMENTAL", ["Drug: Semaglutide"])],
    )
    wrong = _report(
        "Currently recruiting or active trials include NCT00000011.", [completed]
    )
    assert _severity(wrong, "TRIAL_STATUS_MISMATCH") == {"error"}


# ---------------------------------------------------------------------------
# 3 — drug-specific pharmacokinetic assessments in NCT05671653
# ---------------------------------------------------------------------------


def test_two_cohort_pk_study_is_attributed_by_arm_not_by_proximity(pk_trial):
    """Each cohort is separate: the record registers one study drug per cohort."""
    assert [a.label for a in pk_trial.arm_groups] == [
        "Cohort 1: PF-07081532",
        "Cohort 2: Semaglutide",
    ]
    assert {d.name: d.role for d in pk_trial.intervention_details} == {
        "PF-07081532": "EXPERIMENTAL",
        "Semaglutide": "EXPERIMENTAL",
    }

    attribution = attribute_trials([pk_trial], QUERY)
    record = next(r for r in attribution.records if r.nct_id == pk_trial.nct_id)
    assert record.category == DIRECT
    assert record.matched_interventions == ["Semaglutide"]
    assert record.registry_roles == ["EXPERIMENTAL"]


def test_contraceptive_assessments_are_not_attributed_to_the_semaglutide_cohort(
    pk_trial,
):
    """The hormonal-contraceptive readings belong to the cohort the registry names."""
    contraceptive_measures = [
        o.measure for o in pk_trial.outcomes if "contracepti" in o.measure.lower()
        or "levonorgestrel" in o.measure.lower()
        or "ethinyl estradiol" in o.measure.lower()
    ]
    assert contraceptive_measures, "the captured record lists its contraceptive PK"
    assert all(
        measure.lower().startswith("cohort 1")
        for measure in contraceptive_measures
    ), "a contraceptive reading filed under another cohort would need re-reading"
    assert not any(
        "cohort 2" in measure.lower() and "semaglutide" in measure.lower()
        for measure in contraceptive_measures
    )

    # The payload shows the model which arm read which drug, and the gate rejects a
    # sentence that pairs products the record never co-registered.
    payload = _payload([pk_trial])
    row = payload["clinical_trials"][0]
    assert any(
        measure.startswith("[") for measure in row["registry_outcome_measures"]
    )
    assert any(
        "Levonorgestrel" in measure
        for measure in row["registry_outcome_measures"]
        if "Cohort" in measure
    )

    both = _report(
        f"{pk_trial.nct_id} assessed the pharmacokinetic interaction between "
        "PF-07081532 and semaglutide.",
        [pk_trial],
    )
    assert _severity(both, "TRIAL_INTERACTION_UNSUPPORTED") == {"error"}
    assert both.blocked is True

    absent = _report(
        f"In {pk_trial.nct_id}, semaglutide was co-administered with "
        "levonorgestrel.",
        [pk_trial],
    )
    assert _severity(absent, "TRIAL_INTERACTION_UNSUPPORTED") == {"error"}

    single = _report(
        f"In {pk_trial.nct_id}, cohort 2 received semaglutide.", [pk_trial]
    )
    assert _matches(single, "TRIAL_INTERACTION_UNSUPPORTED") == []


def test_products_registered_in_one_arm_are_not_flagged(pk_trial):
    """The rule needs a record that files both products in the same arm."""
    combination = _trial(
        "NCT99999999",
        interventions=[
            _intervention("Semaglutide + metformin", "DRUG", "EXPERIMENTAL", ["A"]),
        ],
        arms=[_arm("A", "EXPERIMENTAL", ["Drug: Semaglutide + metformin"])],
    )
    report = _report(
        "NCT99999999 combined semaglutide with metformin in one arm.",
        [combination, pk_trial],
    )
    assert _matches(report, "TRIAL_INTERACTION_UNSUPPORTED") == []


# ---------------------------------------------------------------------------
# 4 — publication counts against classification totals
# ---------------------------------------------------------------------------


def test_publication_count_and_class_total_reconcile_on_one_denominator():
    """25 publications plus 12 label passages are 37 records, stated as such."""
    evidence = [
        _publication(i, EvidenceType.randomized_controlled_trial) for i in range(20)
    ] + [
        _publication(100 + i, EvidenceType.clinical) for i in range(4)
    ] + [
        _publication(200, EvidenceType.other)
    ] + [
        _label_passage(i) for i in range(1, 13)
    ]
    strength = compute_evidence_strength(evidence)

    assert strength.publication_records == 25
    assert strength.regulatory_passages == 12
    assert strength.total_records == 37
    assert strength.reconciles is True
    assert strength.mutually_exclusive is True
    # Every class states the unit it counts, so 37 cannot read as 37 publications.
    assert {c.unit for c in strength.categories} == {"publication", "label passage"}
    assert "25 publication" in strength.denominator
    assert "37 retrieved evidence record" in strength.denominator

    report = _report(
        "The tables list 37 records and 25 publications.",
        [],
        field="literature_summary",
        identifiers=collect_identifiers(evidence),
        evidence_strength=strength,
    )
    assert _matches(report, "COUNT_NOT_IN_RETRIEVAL") == []
    assert _matches(report, "ARITHMETIC_UNRECONCILED") == []


def test_a_class_total_that_overshoots_the_records_is_an_error():
    """Overlapping categories are reported, not quietly summed."""
    strength = compute_evidence_strength(
        [_publication(i, EvidenceType.clinical) for i in range(5)]
    )
    broken = strength.model_copy(
        update={"categories": [*strength.categories, *strength.categories]}
    )
    assert broken.reconciles is False or sum(
        c.count for c in broken.categories
    ) != broken.total_records

    report = _report("Five records were retrieved.", [], evidence_strength=broken)
    assert _severity(report, "ARITHMETIC_UNRECONCILED") == {"error"}
    assert report.blocked is True


def test_a_count_no_retrieved_record_supports_is_rejected():
    strength = compute_evidence_strength(
        [_publication(i, EvidenceType.observational) for i in range(10)]
    )
    report = _report(
        "The dossier draws on 37 published studies.",
        [],
        field="literature_summary",
        evidence_strength=strength,
    )
    assert _severity(report, "COUNT_NOT_IN_RETRIEVAL") == {"error"}
    assert report.blocked is True


# ---------------------------------------------------------------------------
# 5 — "30+ real-world studies" must be reproducible from the record list
# ---------------------------------------------------------------------------


def _design_count(strength, needle: str):
    return next(d for d in strength.study_design_counts if needle in d.label)


def test_real_world_claim_needs_a_qualifying_record_list():
    """A study-design count is only quotable when the records behind it exist."""
    qualifying = [
        _publication(i, EvidenceType.observational) for i in range(30)
    ]
    strength = compute_evidence_strength(qualifying)
    real_world = _design_count(strength, "Real-world")

    assert real_world.count == 30
    assert len(real_world.records) == 30
    assert real_world.denominator == "30 publication(s) retrieved"

    allowed = _report(
        "The retrieved set contains 30 real-world studies.",
        [],
        field="literature_summary",
        evidence_strength=strength,
    )
    assert _matches(allowed, "COUNT_NOT_IN_RETRIEVAL") == []

    short = compute_evidence_strength(qualifying[:25])
    refused = _report(
        "The retrieved set contains 30 real-world studies.",
        [],
        field="literature_summary",
        evidence_strength=short,
    )
    assert _severity(refused, "COUNT_NOT_IN_RETRIEVAL") == {"error"}
    # And the design tally itself shows the shortfall, rather than a rounded-up claim.
    assert _design_count(short, "Real-world").count == 25


# ---------------------------------------------------------------------------
# 6 — irrelevant or weakly attributable records stay out of product counts
# ---------------------------------------------------------------------------


def test_title_only_matches_are_excluded_from_product_specific_counts():
    title_only = _trial(
        "NCT05984238",
        title="Semaglutide weight loss after duodenal pulsed electric field therapy",
        conditions=["Obesity"],
        interventions=[_intervention("Duodenal PEF procedure", "DEVICE")],
        arms=[_arm("A", "EXPERIMENTAL", ["Procedure: Duodenal PEF procedure"])],
    )
    class_only = _trial(
        "NCT07732738",
        title="GLP-1 receptor agonist in type 2 diabetes",
        conditions=["Diabetes"],
        interventions=[_intervention("Liraglutide", "DRUG", "EXPERIMENTAL", ["A"])],
        arms=[_arm("A", "EXPERIMENTAL", ["Drug: Liraglutide"])],
    )
    named = _trial(
        "NCT04777409",
        interventions=[
            _intervention("Semaglutide", "DRUG", "EXPERIMENTAL", ["A"]),
            _intervention("Placebo", "DRUG", "PLACEBO_COMPARATOR", ["B"]),
        ],
        arms=[
            _arm("A", "EXPERIMENTAL", ["Drug: Semaglutide"]),
            _arm("B", "PLACEBO_COMPARATOR", ["Drug: Placebo"]),
        ],
    )

    # Berobenatide shares a study with the queried product, so the registry — not
    # a drug-class table — is what makes it a companion.
    co_registered = _trial(
        "NCT05671653",
        interventions=[
            _intervention("Berobenatide", "DRUG", "EXPERIMENTAL", ["A"]),
            _intervention("Semaglutide", "DRUG", "EXPERIMENTAL", ["B"]),
        ],
        arms=[
            _arm("A", "EXPERIMENTAL", ["Drug: Berobenatide"]),
            _arm("B", "EXPERIMENTAL", ["Drug: Semaglutide"]),
        ],
    )
    companion_only = _trial(
        "NCT08888888",
        title="Berobenatide in heart failure",
        conditions=["Heart Failure"],
        interventions=[_intervention("Berobenatide", "DRUG", "EXPERIMENTAL", ["A"])],
        arms=[_arm("A", "EXPERIMENTAL", ["Drug: Berobenatide"])],
    )

    attribution = attribute_trials(
        [named, co_registered, class_only, title_only, companion_only], QUERY
    )
    categories = {r.nct_id: r.category for r in attribution.records}

    assert categories[NCT_ALZHEIMER] == DIRECT
    assert categories[NCT_PK] == DIRECT
    assert categories["NCT08888888"] == RELATED_NOT_NAMED
    assert categories["NCT05984238"] == RELATED_NOT_NAMED
    # Another molecule in the same class is not related *by these records*.
    assert categories["NCT07732738"] == NOT_DEMONSTRABLY_RELEVANT
    # Only the records that register the product count as studies of it.
    assert attribution.query_specific_trials == 2
    assert attribution.direct_trials == 2
    assert attribution.excluded_nct_ids == ["NCT07732738", "NCT05984238", "NCT08888888"]
    assert attribution.distinct_trials == 5
    # Every excluded record carries the structured evidence that placed it there.
    for record in attribution.records:
        if record.category in (RELATED_NOT_NAMED, NOT_DEMONSTRABLY_RELEVANT):
            assert record.basis
    companion_record = next(
        r for r in attribution.records if r.nct_id == "NCT08888888"
    )
    assert "NCT05671653" in companion_record.basis

    # A placebo arm named after the product does not demote the study either.
    masked = _trial(
        "NCT06666666",
        interventions=[
            _intervention("Semaglutide", "DRUG", "EXPERIMENTAL", ["A"]),
            _intervention("Placebo (semaglutide)", "DRUG", "PLACEBO_COMPARATOR", ["B"]),
        ],
        arms=[
            _arm("A", "EXPERIMENTAL", ["Drug: Semaglutide"]),
            _arm("B", "PLACEBO_COMPARATOR", ["Drug: Placebo (semaglutide)"]),
        ],
    )
    masked_attribution = attribute_trials([masked], QUERY)
    assert masked_attribution.direct_trials == 1
    assert masked_attribution.comparator_or_combination_trials == 0


def test_comparator_only_registration_is_its_own_category(psoriasis_trial):
    """A record where the product is the comparator is not a study of the product."""
    attribution = attribute_trials([psoriasis_trial], QUERY)
    record = next(r for r in attribution.records if r.nct_id == psoriasis_trial.nct_id)
    assert record.category == COMPARATOR_OR_COMBINATION
    assert record.registry_roles == ["ACTIVE_COMPARATOR"]
    assert attribution.direct_trials == 0


# ---------------------------------------------------------------------------
# 7 — placebo, sham, procedure, comparator and combination counts apart
# ---------------------------------------------------------------------------


def test_masked_procedure_comparator_and_combination_counts_are_separate():
    trials = [
        _trial(
            "NCT00000001",
            interventions=[
                _intervention("Semaglutide", "DRUG", "EXPERIMENTAL", ["A"]),
                _intervention("Placebo", "DRUG", "PLACEBO_COMPARATOR", ["B"]),
            ],
            arms=[
                _arm("A", "EXPERIMENTAL", ["Drug: Semaglutide"]),
                _arm("B", "PLACEBO_COMPARATOR", ["Drug: Placebo"]),
            ],
        ),
        _trial(
            "NCT00000002",
            interventions=[
                _intervention("Sham procedure", "DEVICE", "SHAM_COMPARATOR", ["C"]),
                _intervention("Xanomeline", "DRUG", None, ["D"]),
            ],
            arms=[
                _arm("C", "SHAM_COMPARATOR", ["Device: Sham procedure"]),
                _arm("D", "EXPERIMENTAL", ["Drug: Xanomeline"]),
            ],
        ),
        _trial(
            "NCT00000004",
            interventions=[
                _intervention("Semaglutide", "DRUG", "ACTIVE_COMPARATOR", ["E"]),
                _intervention("Metformin", "DRUG", "EXPERIMENTAL", ["F"]),
            ],
            arms=[
                _arm("E", "ACTIVE_COMPARATOR", ["Drug: Semaglutide"]),
                _arm("F", "EXPERIMENTAL", ["Drug: Metformin"]),
            ],
        ),
        _trial(
            "NCT00000005",
            interventions=[
                _intervention("Semaglutide + metformin", "DRUG", "EXPERIMENTAL", ["G"]),
            ],
            arms=[
                _arm("G", "EXPERIMENTAL", ["Drug: Semaglutide + metformin"])
            ],
        ),
    ]
    labels = [_label_passage(1)]
    candidates = compute_candidates(trials, _metadata(len(trials)), labels)
    attribution = attribute_trials(trials, QUERY)

    # A masked control is counted as a control, not as a candidate in development.
    assert attribution.placebo_or_sham_arms == 2
    assert "placebo" in attribution.placebo_or_sham_names
    # A procedure never enters a drug-candidate list; it is typed where it sits.
    assert {b.label: b.count for b in candidates.non_drug_intervention_types} == {
        "Device": 1
    }
    # Registry roles, not name wording, decide who is a comparator. "Semaglutide"
    # is an active comparator in one study and experimental in another, so the
    # registry gives it no single role and it is never filed as a control.
    comparator_names = {
        r.name for r in candidates.records if _is_comparator(r)
    }
    assert {"Placebo"} <= comparator_names
    semaglutide_record = next(r for r in candidates.records if r.name == "Semaglutide")
    assert set(semaglutide_record.registry_roles) == {"EXPERIMENTAL", "ACTIVE_COMPARATOR"}
    assert semaglutide_record.name not in comparator_names
    assert _is_comparator(next(r for r in candidates.records if r.name == "Placebo"))
    # A combination product is its own record, never merged into either substance.
    assert "Semaglutide + metformin" in {r.name for r in candidates.records}
    assert "Semaglutide" in {r.name for r in candidates.records}
    # A marketed product is identified from a retrieved label, not from a guess.
    assert candidates.candidates_with_openfda_label <= candidates.distinct_candidates
    assert candidates.counting_rule

    # The headline number never mixes the four kinds.
    assert candidates.distinct_candidates == len(candidates.records)
    assert sum(c.count for c in attribution.categories) == attribution.distinct_trials


def _is_comparator(record) -> bool:
    from services.candidate_analytics import is_registered_comparator

    return is_registered_comparator(record)


# ---------------------------------------------------------------------------
# 8 — raw status categories sum to the distinct trials; ongoing does not
# ---------------------------------------------------------------------------


def test_status_categories_partition_the_captured_records(semaglutide_trials):
    analytics = compute_analytics(semaglutide_trials, _metadata(3))

    assert analytics.total_trials == 3
    assert analytics.statuses_reconcile is True
    assert sum(g.count for g in analytics.status_groups) == analytics.total_trials
    # A derived grouping is defined by the raw statuses inside it, and no raw
    # status appears in two groups.
    memberships = [g.registry_statuses for g in analytics.status_groups]
    flat = [s for group in memberships for s in group]
    assert len(flat) == len(set(flat))
    # Ongoing is a derived read across categories, never an extra row.
    assert analytics.ongoing_trials == (
        analytics.currently_recruiting_trials + analytics.active_not_recruiting_trials
    )
    assert analytics.exclusive_status_total == analytics.total_trials
    assert "never added" in analytics.ongoing_definition

    report = _report(
        "Three distinct studies were retrieved.",
        semaglutide_trials,
        analytics=analytics,
    )
    assert _matches(report, "ARITHMETIC_UNRECONCILED") == []


def test_overlapping_status_rows_are_reported_as_unreconciled():
    analytics = compute_analytics([], _metadata(0))
    assert analytics.total_trials == 0
    broken = analytics.model_copy(
        update={
            "total_trials": 2,
            "statuses_reconcile": False,
            "exclusive_status_total": 1,
        }
    )
    report = _report("Records were retrieved.", [], analytics=broken)
    assert _severity(report, "ARITHMETIC_UNRECONCILED") == {"error"}


# ---------------------------------------------------------------------------
# 9 — an endpoint cannot be moved between time points
# ---------------------------------------------------------------------------


def test_a_68_week_endpoint_is_not_rendered_as_six_months():
    trial = _trial(
        "NCT06548677",
        interventions=[_intervention("Semaglutide", "DRUG", "EXPERIMENTAL", ["A"])],
        arms=[_arm("A", "EXPERIMENTAL", ["Drug: Semaglutide"])],
        start_date="2019-06-01",
        completion_date="2021-08-01",
        time_frames=["From baseline (week 0) to week 68"],
    )
    six_months = _report(
        "In NCT06548677, weight loss of 15% was observed at six months.",
        [trial],
    )
    assert _severity(six_months, "TRIAL_DURATION_CONTRADICTS_CLAIM") == {"error"}
    assert six_months.blocked is True

    stated = _report(
        "In NCT06548677, weight was reported at 68 weeks.",
        [trial],
    )
    assert _matches(stated, "TRIAL_DURATION_CONTRADICTS_CLAIM") == []


def test_time_point_rule_is_quiet_when_the_record_states_no_time_frame():
    """A study that lists no outcome visits cannot be contradicted on this rule."""
    assert _fixture(NCT_ALZHEIMER).outcome_time_frames == [
        "From baseline (week 0) to week 104",
        "From baseline (week 0) to week 156",
        "From baseline (week 0) up to week 156",
    ]
    thin = _trial(
        "NCT00000009",
        title="Semaglutide in heart failure",
        interventions=[_intervention("Semaglutide", "DRUG", "EXPERIMENTAL", ["A"])],
        arms=[_arm("A", "EXPERIMENTAL", ["Drug: Semaglutide"])],
        start_date="2019-01-01",
        completion_date="2023-01-01",
    )
    assert thin.outcome_time_frames == []
    report = _report("In NCT00000009, a six month reading was recorded.", [thin])
    assert _matches(report, "TRIAL_DURATION_CONTRADICTS_CLAIM") == []


def test_captured_study_periods_are_checked_against_registry_dates(
    psoriasis_trial,
):
    """A result placed outside the record's own span is an error."""
    inside = _report(
        f"In {NCT_PSORIASIS}, change in body weight was read at 12 weeks.",
        [psoriasis_trial],
    )
    assert _matches(inside, "TRIAL_DURATION_CONTRADICTS_CLAIM") == []

    outside = _report(
        f"In {NCT_PSORIASIS}, a six month result showed improved PASI.",
        [psoriasis_trial],
    )
    assert _severity(outside, "TRIAL_DURATION_CONTRADICTS_CLAIM") == {"error"}


# ---------------------------------------------------------------------------
# 10 — spontaneous reporting is not incidence or causation
# ---------------------------------------------------------------------------


def test_faers_signal_language_is_blocked_and_hedged_language_is_not():
    causal = _report(
        "FAERS reports show that the drug causes acute pancreatitis, with an "
        "increased risk in the first year.",
        [],
        field="safety",
    )
    assert _severity(causal, "REPORTING_SIGNAL_OVERCLAIM") == {"error"}
    assert causal.blocked is True

    hedged = _report(
        "FAERS contains case reports of pancreatitis; spontaneous reporting cannot "
        "establish incidence or causality.",
        [],
        field="safety",
    )
    assert _matches(hedged, "REPORTING_SIGNAL_OVERCLAIM") == []


def test_a_reporting_sentence_without_a_non_causal_qualifier_is_a_warning():
    naked = _report(
        "The pharmacovigilance signal was detected in post-marketing reports.",
        [],
        field="safety",
    )
    assert _severity(naked, "REPORTING_SIGNAL_OVERCLAIM") == {"warning"}
    assert naked.blocked is False


# ---------------------------------------------------------------------------
# 11 — a label warning keeps the uncertainty the source states
# ---------------------------------------------------------------------------


def test_preclinical_thyroid_wording_keeps_human_relevance_open():
    bare = _report(
        "In rodent studies, the drug caused thyroid C-cell tumours.",
        [],
        field="safety",
    )
    assert _severity(bare, "PRECLINICAL_HUMAN_RELEVANCE") == {"warning"}

    qualified = _report(
        "In rodent studies the drug produced thyroid C-cell tumours; the relevance "
        "of this finding to people is uncertain.",
        [],
        field="safety",
    )
    assert _matches(qualified, "PRECLINICAL_HUMAN_RELEVANCE") == []


def test_a_labelling_claim_without_a_named_product_is_an_error():
    """Separately approved products of one molecule do not share indications."""
    report = _report(
        "The boxed warning contraindicates use in patients with MEN 2.",
        [],
        field="safety",
        label_products=[],
    )
    assert _severity(report, "LABEL_CLAIM_WITHOUT_PRODUCT") == {"error"}
    assert report.blocked is True

    attributed = _report(
        "Ozempic's boxed warning contraindicates use in patients with MEN 2.",
        [],
        field="safety",
        label_products=["ozempic"],
    )
    assert _matches(attributed, "LABEL_CLAIM_WITHOUT_PRODUCT") == []


# ---------------------------------------------------------------------------
# 12 — a histological reading is not a proven clinical benefit
# ---------------------------------------------------------------------------


def test_surrogate_mash_outcome_is_not_stated_as_proven_long_term_benefit():
    overclaim = _report(
        "Steatohepatitis resolution on biopsy demonstrated proven long-term benefit "
        "in MASH.",
        [],
        field="therapeutic_evidence",
    )
    assert _severity(overclaim, "SURROGATE_ENDPOINT_OVERCLAIM") == {"warning"}

    bounded = _report(
        "Steatohepatitis resolution on biopsy is the endpoint the trial measured; "
        "a hard clinical outcome was not assessed.",
        [],
        field="therapeutic_evidence",
    )
    assert _matches(bounded, "SURROGATE_ENDPOINT_OVERCLAIM") == []


# ---------------------------------------------------------------------------
# 13 — partial retrieval is visible and never called comprehensive
# ---------------------------------------------------------------------------


def test_partial_retrieval_is_a_finding_and_a_coverage_claim_is_blocked():
    trials = [_fixture(NCT_PSORIASIS)]
    sources = [
        SourceStatus(
            source_name="ClinicalTrials.gov",
            status="success",
            count=50,
            note="50 of a larger result set",
        )
    ]
    partial = _report(
        f"{NCT_PSORIASIS} is recruiting.",
        trials,
        sources=sources,
        partial_retrieval=True,
    )
    assert "RETRIEVAL_INCOMPLETE" in _rules(partial)
    assert partial.blocked is False  # a capped result set is disclosed, not hidden

    overstated = _report(
        "A comprehensive search found every trial of the product.",
        trials,
        sources=sources,
        partial_retrieval=True,
    )
    severities = _severity(overstated, "RETRIEVAL_INCOMPLETE")
    # The capped set is still disclosed as a warning, and the coverage claimed on
    # top of it is the error that blocks publication.
    assert severities == {"error", "warning"}
    assert overstated.blocked is True

    complete = _report(
        f"{NCT_PSORIASIS} is recruiting.",
        trials,
        sources=sources,
        partial_retrieval=False,
    )
    assert _matches(complete, "RETRIEVAL_INCOMPLETE") == []


def test_a_source_that_could_not_be_consulted_is_separate_from_zero_records():
    trials = [_fixture(NCT_PSORIASIS)]
    failed = _report(
        "No safety signal was identified.",
        trials,
        field="safety",
        sources=[
            SourceStatus(
                source_name="openFDA",
                status="error",
                error_message="503 from the label endpoint",
            )
        ],
    )
    assert _severity(failed, "SOURCE_NOT_CONSULTED") == {"warning"}

    empty = _report(
        "No label records were returned for these terms.",
        trials,
        field="safety",
        sources=[SourceStatus(source_name="openFDA", status="no_results", count=0)],
    )
    assert _severity(empty, "SOURCE_NOT_CONSULTED") == {"warning"}

    # "Nothing returned" is not "nothing exists".
    overclaimed = _report(
        "No evidence exists for this question.",
        trials,
        field="evidence_gaps",
    )
    assert _severity(overclaimed, "ABSENCE_OVERCLAIM") == {"error"}


def test_a_skipped_source_is_not_reported_as_a_failure():
    trials = [_fixture(NCT_PSORIASIS)]
    report = _report(
        f"{NCT_PSORIASIS} is recruiting.",
        trials,
        sources=[SourceStatus(source_name="UniProt", status="skipped", count=0)],
    )
    assert _matches(report, "SOURCE_NOT_CONSULTED") == []


# ---------------------------------------------------------------------------
# 14 — an unsupported numeric claim is blocked, not repaired
# ---------------------------------------------------------------------------


def test_an_unsourced_figure_is_blocked_and_a_recorded_one_is_not():
    trial = _fixture(NCT_ALZHEIMER)
    unsourced = _report(
        "HbA1c fell by 1.5% at six months.",
        [trial],
    )
    assert _severity(unsourced, "NUMERIC_CLAIM_UNSOURCEDED") == {"error"}
    assert unsourced.blocked is True
    finding = unsourced.findings[0]
    assert finding.suggested_correction
    assert "name" in finding.suggested_correction.lower()

    # A population figure has to match the registry's own enrollment number.
    wrong = _report(f"{NCT_ALZHEIMER} enrolled 500 participants.", [trial])
    assert _severity(wrong, "TRIAL_POPULATION_MISMATCH") == {"error"}
    right = _report(f"{NCT_ALZHEIMER} enrolled 1840 participants.", [trial])
    assert _matches(right, "TRIAL_POPULATION_MISMATCH") == []


def test_a_citation_to_a_record_that_was_never_retrieved_is_an_error():
    trial = _fixture(NCT_ALZHEIMER)
    report = _report(
        "PMID:99999999 reports the same finding.",
        [trial],
        field="literature_summary",
        identifiers=["PMID:12345678"],
    )
    assert _severity(report, "FABRICATED_IDENTIFIER") == {"error"}
    assert report.blocked is True

    nct = _report(
        "NCT00000001 studied the same question.", [trial]
    )
    assert _matches(nct, "FABRICATED_IDENTIFIER") == ["NCT00000001 studied the same question."]


# ---------------------------------------------------------------------------
# 15 — deduplication must not double-count
# ---------------------------------------------------------------------------


def test_the_same_publication_is_counted_once_after_deduplication():
    pmid = "35000001"
    duplicates = [
        EvidenceItem(
            source="PubMed",
            source_type="literature",
            id=pmid,
            title="A trial of the product",
            url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
            evidence_type=EvidenceType.randomized_controlled_trial,
            metadata={"pmid": pmid},
        ),
        EvidenceItem(
            source="Europe PMC",
            source_type="literature",
            id=f"{pmid}_epmc",
            title="A trial of the product",
            url=f"https://europepmc.org/article/MED/{pmid}",
            evidence_type=EvidenceType.randomized_controlled_trial,
            metadata={"pmid": pmid},
        ),
    ]
    merged = deduplicate(duplicates)
    assert len(merged) == 1

    strength = compute_evidence_strength(merged)
    assert strength.total_records == 1
    assert strength.publication_records == 1
    assert sum(c.count for c in strength.categories) == 1
    assert strength.reconciles is True


def test_the_same_trial_is_counted_once_in_every_aggregate():
    trial = _fixture(NCT_PSORIASIS)
    analytics = compute_analytics([trial, trial], _metadata(2))
    attribution = attribute_trials([trial, trial], QUERY)

    assert analytics.total_trials == 1
    assert sum(g.count for g in analytics.status_groups) == 1
    assert attribution.distinct_trials == 1
    assert sum(c.count for c in attribution.categories) == 1

    candidates = compute_candidates([trial, trial], _metadata(2))
    assert {r.name for r in candidates.records} == {
        "Semaglutide (Rybelsus®)",
        "Placebo",
    }


# ---------------------------------------------------------------------------
# The gate's own contract (§9): every declared rule runs and nothing is repaired
# ---------------------------------------------------------------------------


def test_the_gate_reports_machine_readable_output_and_never_edits_the_narrative(
    semaglutide_trials,
):
    narrative = (
        f"{NCT_ALZHEIMER} was a Phase 2 trial. A comprehensive search covers every "
        "study. FAERS shows the drug causes pancreatitis."
    )
    dossier = Dossier(
        query=QUERY,
        clinical_development=narrative,
        safety="FAERS reporting shows the drug causes pancreatitis.",
        evidence_gaps="Nothing is known about long-term use.",
        research_gap_analysis=[
            ResearchGap(
                question="Does the product reduce fractures?",
                current_evidence="No trial in this set measured fractures.",
                uncertainty="Unstudied.",
                why_it_matters="Fractures matter for older patients.",
                next_step="A trial with a fracture endpoint.",
            )
        ],
        contradictory_findings=ContradictoryFindings(
            assessment="potentially_conflicting",
            contradictions=[
                Contradiction(
                    claim="Weight loss at six months",
                    study_a=f"{NCT_PSORIASIS} reads the endpoint at week 12",
                    study_b="A 68-week result",
                    possible_explanation="Different populations.",
                )
            ],
        ),
    )
    report = validate_dossier(
        dossier,
        semaglutide_trials,
        identifiers=collect_identifiers([]),
        label_products=collect_label_products([]),
        partial_retrieval=True,
    )

    assert report.errors > 0
    assert report.blocked is True
    # Every finding is actionable: rule, severity, place, and what to fix.
    for finding in report.findings:
        assert finding.rule in RULES
        assert finding.severity in ("error", "warning")
        assert finding.field
        if finding.field in _NARRATIVE_FIELDS:
            assert finding.quote
        else:
            # An aggregate-level finding has no sentence to quote; it names the
            # figure the reader is shown instead.
            assert finding.observed
        assert finding.expected and finding.observed
        assert finding.suggested_correction
        assert finding.status == "fail"
        assert finding.blocks_publication == (finding.severity == "error")
    # Findings are also drawn from the structured narrative sections, not only prose.
    fields = {f.field for f in report.findings}
    assert any(field.startswith("research_gap_analysis") for field in fields)
    assert any(field.startswith("contradictory_findings") for field in fields)

    # Validation never rewrites: the report is a separate object.
    assert dossier.clinical_development == narrative
    assert report.rules_run == list(RULES)
    assert len(RULES) == 18


def test_every_declared_rule_can_fire():
    """A rule listed in the contract must exist in this module's findings.

    The ids are compared against the sentences each rule was written for, so a
    rule that was declared and never wired shows up as a missing id here.
    """
    covered = set()
    trials = [_fixture(NCT_ALZHEIMER), _fixture(NCT_PK)]
    strength = compute_evidence_strength([_publication(1, EvidenceType.other)])
    analytics = compute_analytics(trials, _metadata(1, partial=True))
    attribution = attribute_trials(trials, QUERY)
    sources = [
        SourceStatus(source_name="openFDA", status="error", error_message="503"),
        SourceStatus(source_name="UniProt", status="no_results"),
    ]
    report = validate_dossier(
        Dossier(
            query=QUERY,
            clinical_development=(
                f"{NCT_ALZHEIMER} was a Phase 2 trial that is recruiting, enrolled "
                "999 participants, and reported a result at six months. "
                f"{NCT_PK} assessed the interaction between PF-07081532 and "
                "semaglutide. Weight loss of 15% was reported. A comprehensive "
                "search covered all trials. There are 400 published studies. "
                "FAERS proves an increased risk. The boxed warning contraindicates "
                "MEN 2. Rodents developed thyroid tumours. Biopsy resolution "
                "demonstrated proven long-term benefit. No evidence exists for "
                "this. PMID:99999999 agrees."
            ),
        ),
        trials,
        identifiers=["PMID:12345678"],
        label_products=[],
        evidence_strength=strength,
        analytics=analytics,
        attribution=attribution,
        sources=sources,
        partial_retrieval=True,
    )
    covered |= _rules(report)

    # The arithmetic rules need aggregates that do not reconcile.
    broken_strength = strength.model_copy(
        update={"categories": [*strength.categories, *strength.categories]}
    )
    covered |= _rules(
        validate_dossier(
            Dossier(query=QUERY, literature_summary="Records were retrieved."),
            [],
            evidence_strength=broken_strength,
        )
    )
    covered |= {
        f.rule
        for f in validate_dossier(
            Dossier(query=QUERY),
            [
                _trial("NCT00000009").model_copy(
                    update={"source_url": None, "retrieved_at": None}
                )
            ],
        ).findings
    }

    assert covered >= set(RULES), f"declared but unfired rules: {set(RULES) - covered}"


# ---------------------------------------------------------------------------
# Optional live check — ordinary runs never reach the network
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    os.getenv("MOLTEL_LIVE_TESTS") != "1",
    reason="opt-in live check: set MOLTEL_LIVE_TESTS=1 to detect registry schema drift",
)
async def test_live_registry_still_publishes_the_fields_this_pipeline_reads():
    """The fixtures freeze what the registry said on 2026-10-29.

    A field the registry renames would silently empty a panel rather than raise,
    so this one check runs against the live source on demand and reads only
    structure — no counts, no claims, no model call.
    """
    import httpx

    from integrations.clinicaltrials import BASE_URL

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(
            f"{BASE_URL}/studies",
            params={"query.term": QUERY, "pageSize": "5", "format": "json"},
        )
        response.raise_for_status()
        studies = response.json().get("studies", [])

    assert studies, "the registry returned no studies for a query that has thousands"
    parsed = []
    for study in studies:
        protocol = study.get("protocolSection", {})
        assert isinstance(protocol.get("armsInterventionsModule", {}), dict)
        trial = _parse_study(study, RETRIEVED_AT)
        if trial is not None:
            parsed.append(trial)

    assert parsed
    for trial in parsed:
        assert isinstance(trial.outcome_time_frames, list)
        assert isinstance(trial.arm_groups, list)
        # A record the pipeline can attribute always carries its own registry id.
        assert trial.nct_id.startswith("NCT")
