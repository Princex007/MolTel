"""Pipeline tests for the research orchestrator and the /api/trials route.

The scientific integrations are stubbed at their module boundary and the LLM is
never contacted, so these tests assert how the pipeline reports a failing,
skipped or empty source rather than what any external API returns.
"""

from __future__ import annotations

import httpx
import pytest
import respx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api import dossier as dossier_api
from api import trials as trials_api
from integrations import (
    clinicaltrials,
    disease_ontology,
    europepmc,
    openfda,
    pubchem,
    pubmed,
    uniprot,
)
from models.schemas import (
    ClinicalTrial,
    CompoundProfile,
    DiseaseConcept,
    DiseaseTerm,
    DossierResponse,
    EvidenceItem,
    EvidenceType,
    SearchMode,
    TargetProfile,
    TrialIntervention,
    TrialRetrievalMetadata,
)
from services import trial_taxonomy
from services.dossier_generator import DossierResult, build_data_dossier
from services.research_orchestrator import ResearchOrchestrator

CT_STUDIES_URL = "https://clinicaltrials.gov/api/v2/studies"

_COMPOUND = CompoundProfile(cid="12345", name="drug x")


def _literature(item_id: str, source: str = "EuropePMC") -> EvidenceItem:
    return EvidenceItem(
        source=source,
        source_type="literature",
        id=item_id,
        title=f"Trial of drug X ({item_id})",
        year=2024,
        evidence_type=EvidenceType.clinical,
        url=f"https://europepmc.org/article/{item_id}",
    )


def _trial(nct_id: str, status: str, phases: list[str] | None = None) -> ClinicalTrial:
    phases = ["PHASE2"] if phases is None else phases
    return ClinicalTrial(
        nct_id=nct_id,
        title=f"Study {nct_id}",
        status=trial_taxonomy.status_label(status),
        overall_status=status,
        status_category=trial_taxonomy.status_category(status),
        ongoing=trial_taxonomy.is_ongoing(status),
        phases=phases,
        phase_category=trial_taxonomy.phase_category(phases),
        conditions=["Condition Y"],
    )


def _install(
    monkeypatch,
    *,
    trials_result=(),
    trials_error: BaseException | None = None,
    literature: list[EvidenceItem] | None = None,
    literature_error: BaseException | None = None,
    pubmed_items: list[EvidenceItem] | None = None,
    regulatory: list[EvidenceItem] | None = None,
    concept: DiseaseConcept | BaseException | None = None,
    targets: list[TargetProfile] | None = None,
):
    """Replace every integration so no test can reach the network."""
    literature = literature if literature is not None else [_literature("U1"), _literature("U2")]

    async def compound_ok(query):
        return _COMPOUND

    async def literature_ok(query):
        if literature_error:
            raise literature_error
        return literature

    async def literature_empty(query):
        return pubmed_items or []

    async def regulatory_stub(query):
        return regulatory or []

    async def trials_stub(query):
        if trials_error:
            raise trials_error
        if trials_result:
            return trials_result
        return (
            [_trial("NCT1", "RECRUITING"), _trial("NCT2", "COMPLETED")],
            TrialRetrievalMetadata(query=query, source_reached=True, records_returned=2),
        )

    async def targets_ok(query):
        return targets or []

    async def concept_stub(query):
        if isinstance(concept, BaseException):
            raise concept
        return concept or DiseaseConcept(
            query=query, source_reached=False, note="stubbed lookup"
        )

    monkeypatch.setattr(pubchem, "search_compound", compound_ok)
    monkeypatch.setattr(pubmed, "search_literature", literature_empty)
    monkeypatch.setattr(europepmc, "search_literature", literature_ok)
    monkeypatch.setattr(openfda, "search_drug_labels", regulatory_stub)
    monkeypatch.setattr(uniprot, "search_target", targets_ok)
    monkeypatch.setattr(clinicaltrials, "fetch_trials", trials_stub)
    monkeypatch.setattr(disease_ontology, "lookup_disease", concept_stub)


@pytest.mark.asyncio
async def test_unreachable_registry_omits_analytics_instead_of_zero_filling(monkeypatch):
    """A registry outage is not evidence that no trials exist."""
    _install(monkeypatch, trials_error=RuntimeError("503 from the registry"))
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    response = await ResearchOrchestrator().orchestrate("drug x")

    statuses = {s.source_name: s for s in response.sources}
    assert statuses["ClinicalTrials.gov"].status == "error"
    assert statuses["EuropePMC"].status == "success"
    assert response.trial_analytics is None
    assert response.status == "partial"
    # The rest of the dossier is still built from the sources that did answer.
    assert response.dossier is not None
    assert response.evidence_strength.categories


@pytest.mark.asyncio
async def test_reachable_registry_with_no_matches_reports_zero_records(monkeypatch):
    """An empty result set is reported as zero retrieved records, with no
    fabricated chart buckets."""
    _install(
        monkeypatch,
        trials_result=(
            [],
            TrialRetrievalMetadata(
                query="drug x", source_reached=True, records_returned=0, partial=True
            ),
        ),
    )
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    response = await ResearchOrchestrator().orchestrate("drug x")

    analytics = response.trial_analytics
    assert analytics is not None
    assert analytics.total_trials == 0
    assert analytics.trials_by_phase == []
    assert analytics.trials_by_status == []
    assert response.status == "partial"
    assert {s.source_name: s.status for s in response.sources}[
        "ClinicalTrials.gov"
    ] == "no_results"


@pytest.mark.asyncio
async def test_analytics_describe_the_same_records_the_table_shows(monkeypatch):
    """Chart totals must match the deduplicated records handed to the UI."""
    _install(
        monkeypatch,
        trials_result=(
            [
                _trial("NCT1", "RECRUITING", ["PHASE2"]),
                _trial("NCT1", "RECRUITING", ["PHASE2"]),
                _trial("NCT2", "ACTIVE_NOT_RECRUITING", ["PHASE1", "PHASE2"]),
                _trial("NCT3", "UNKNOWN", []),
            ],
            TrialRetrievalMetadata(query="drug x", source_reached=True, records_returned=3),
        ),
    )
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    response = await ResearchOrchestrator().orchestrate("drug x")

    a = response.trial_analytics
    distinct = len({t.nct_id for t in response.clinical_trials})
    assert a.total_trials == distinct == 3
    assert (
        a.recruiting_trials
        + a.active_not_recruiting_trials
        + a.not_yet_recruiting_trials
        + a.completed_trials
        + a.discontinued_trials
        + a.paused_trials
        + a.other_status_trials
        == a.total_trials
    )
    assert a.trials_with_unreported_phase == 1


@pytest.mark.asyncio
async def test_candidate_counts_are_distinct_from_trial_counts(monkeypatch):
    """A product studied in two registered trials is one candidate, not two."""

    def with_intervention(nct_id: str, status: str, product: str) -> ClinicalTrial:
        return _trial(nct_id, status).model_copy(
            update={
                "interventions": [product],
                "intervention_details": [TrialIntervention(name=product, type="DRUG")],
            }
        )

    _install(
        monkeypatch,
        trials_result=(
            [
                with_intervention("NCT1", "RECRUITING", "candidate A"),
                with_intervention("NCT2", "COMPLETED", "Candidate A"),
                with_intervention("NCT3", "RECRUITING", "candidate B"),
            ],
            TrialRetrievalMetadata(query="drug x", source_reached=True, records_returned=3),
        ),
        regulatory=[
            EvidenceItem(
                source="openFDA",
                source_type="regulatory",
                title="candidate A — Indications and Usage",
                evidence_type=EvidenceType.regulatory,
                url="https://api.fda.gov/drug/label.json?search=application_number:%22NDA1%22",
                metadata={
                    "label_manufacturer": "Packager Inc",
                    "application_number": "NDA1",
                    "generic_names": ["candidate a"],
                    "brand_names": [],
                },
            )
        ],
    )
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    response = await ResearchOrchestrator().orchestrate("drug x")

    candidates = response.candidate_analytics
    assert candidates is not None
    assert response.trial_analytics.total_trials == 3
    assert candidates.distinct_candidates == 2
    assert candidates.candidate_trials_considered == 3
    assert candidates.candidates_with_established_developer == 0
    assert all(r.developer_note == "Developer not established" for r in candidates.records)
    matched = next(r for r in candidates.records if r.trials == 2)
    assert matched.label_manufacturer == "Packager Inc"
    assert matched.fda_application_number == "NDA1"
    assert candidates.candidates_with_openfda_label == 1


@pytest.mark.asyncio
async def test_dashboard_data_survives_a_failed_ai_synthesis(monkeypatch):
    """The deterministic panels do not depend on the model answering."""
    _install(monkeypatch)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    response = await ResearchOrchestrator().orchestrate("drug x")

    assert response.ai_synthesized is False
    assert response.trial_analytics is not None
    assert response.trial_analytics.total_trials == 2
    assert response.dossier is not None
    assert response.dossier.research_gap_analysis == []
    assert "unavailable" in (response.dossier.contradictory_findings.assessment or "").lower()


# ---------------------------------------------------------------------------
# Search modes (spec §6.1)
# ---------------------------------------------------------------------------


_LUNG_CONCEPT = DiseaseConcept(
    query="lung cancer",
    source_reached=True,
    canonical=DiseaseTerm(
        label="lung cancer",
        concept_id="MONDO:0008903",
        ontology="mondo",
        synonyms=["Lung Neoplasms"],
    ),
    related=[
        DiseaseTerm(label="small cell lung carcinoma", concept_id="MONDO:0008433", ontology="mondo")
    ],
)


def _lung_trials() -> list[ClinicalTrial]:
    return [
        _trial("NCT1", "RECRUITING").model_copy(
            update={
                "conditions": ["Non-small Cell Lung Cancer (NSCLC)"],
                "sponsor": "Merck Sharp",
                "interventions": ["pembrolizumab"],
                "intervention_details": [TrialIntervention(name="pembrolizumab", type="DRUG")],
            }
        ),
        _trial("NCT2", "COMPLETED").model_copy(
            update={"conditions": ["Lung Cancer", "Fatigue"], "sponsor": "AstraZeneca"}
        ),
    ]


@pytest.mark.asyncio
async def test_a_disease_query_skips_the_product_lookups_but_still_reports_success(monkeypatch):
    """A skipped source is a choice about the search mode, not a source failure."""
    _install(
        monkeypatch,
        trials_result=(_lung_trials(), TrialRetrievalMetadata(
            query="lung cancer", source_reached=True, records_returned=2
        )),
        concept=_LUNG_CONCEPT,
        pubmed_items=[_literature("P1", source="PubMed")],
        targets=[TargetProfile(accession="P00001", name="Programmed cell death protein 1")],
    )

    orchestrator = ResearchOrchestrator()

    async def synthesized(**kwargs):
        # The derived aggregates are inputs to the real generator's prompt only;
        # this stub builds the dossier from the records themselves.
        for aggregate in ("analytics", "strength", "attribution"):
            kwargs.pop(aggregate, None)
        return DossierResult(
            dossier=build_data_dossier(**kwargs, reason="synthesis stubbed"),
            synthesized=True,
        )

    monkeypatch.setattr(orchestrator._generator, "generate", synthesized)

    response = await orchestrator.orchestrate("lung cancer", SearchMode.disease)

    assert {s.status for s in response.sources} == {"success", "skipped"}
    assert response.status == "success"
    assert response.ai_synthesized is True


@pytest.mark.asyncio
async def test_a_disease_query_builds_the_disease_view_from_the_same_records(monkeypatch):
    _install(
        monkeypatch,
        trials_result=(_lung_trials(), TrialRetrievalMetadata(
            query="lung cancer", source_reached=True, records_returned=2
        )),
        concept=_LUNG_CONCEPT,
    )
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    response = await ResearchOrchestrator().orchestrate("lung cancer", SearchMode.disease)

    statuses = {s.source_name: s for s in response.sources}
    assert statuses["PubChem"].status == "skipped"
    assert "disease" in (statuses["PubChem"].note or "")
    assert statuses["openFDA"].status == "skipped"
    assert statuses["Disease concept"].status == "success"
    assert response.search_mode is SearchMode.disease
    assert response.dossier is not None
    # No compound is claimed for a disease query.
    assert response.dossier.compound_profile is None

    disease = response.disease_analytics
    assert disease is not None
    assert disease.canonical_term == "lung cancer"
    assert "MONDO:0008903" in disease.canonical_term_provenance
    subtype = disease.subtypes[0]
    assert subtype.label == "Non-small Cell Lung Cancer (NSCLC)"
    assert subtype.trial_nct_ids == ["NCT1"]
    assert subtype.candidate_names == ["pembrolizumab"]
    # A trial-level dashboard is built from the same records as the disease view.
    assert response.trial_analytics is not None
    assert response.trial_analytics.total_trials == disease.trials_considered == 2


@pytest.mark.asyncio
async def test_a_failed_concept_lookup_leaves_the_rest_of_the_pipeline_intact(monkeypatch):
    _install(
        monkeypatch,
        trials_result=(_lung_trials(), TrialRetrievalMetadata(
            query="lung cancer", source_reached=True, records_returned=2
        )),
        concept=RuntimeError("ontology down"),
    )
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    response = await ResearchOrchestrator().orchestrate("lung cancer", SearchMode.disease)

    statuses = {s.source_name: s for s in response.sources}
    assert statuses["Disease concept"].status == "error"
    assert statuses["ClinicalTrials.gov"].status == "success"
    disease = response.disease_analytics
    assert disease is not None
    assert disease.ontology_reached is False
    # Without a concept the dashboard still reports the registry's own wording.
    assert any("could not be consulted" in line for line in disease.limitations)


@pytest.mark.asyncio
async def test_a_compound_query_still_queries_every_source_it_always_did(monkeypatch):
    _install(monkeypatch)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    response = await ResearchOrchestrator().orchestrate("drug x")

    names = [s.source_name for s in response.sources]
    assert names == ["PubChem", "PubMed", "EuropePMC", "ClinicalTrials.gov", "openFDA", "UniProt"]
    assert response.search_mode is SearchMode.compound
    assert response.dossier is not None
    assert response.dossier.compound_profile is not None
    assert response.disease_analytics is None


# ---------------------------------------------------------------------------
# GET /api/trials
# ---------------------------------------------------------------------------


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(trials_api.router, prefix="/api")
    return TestClient(app)


def _study(nct_id, status="RECRUITING", phases=("PHASE2",)):
    return {
        "protocolSection": {
            "identificationModule": {"nctId": nct_id, "briefTitle": f"Study {nct_id}"},
            "statusModule": {"overallStatus": status},
            "designModule": {"studyType": "INTERVENTIONAL", "phases": list(phases)},
            "conditionsModule": {"conditions": ["Alzheimer Disease"]},
        }
    }


@respx.mock
def test_trials_endpoint_analytics_cover_the_unfiltered_set():
    respx.get(CT_STUDIES_URL).mock(
        return_value=httpx.Response(
            200,
            json={"studies": [_study("NCT1"), _study("NCT2", "COMPLETED", ["PHASE3"])]},
        )
    )

    body = _client().get("/api/trials?query=Alzheimer&phase=Phase+3").json()

    assert [t["nct_id"] for t in body["trials"]] == ["NCT2"]
    # The charts describe the whole retrieval, the list carries the filter.
    assert body["analytics"]["total_trials"] == 2
    assert {b["label"]: b["count"] for b in body["analytics"]["trials_by_phase"]} == {
        "Phase 2": 1,
        "Phase 3": 1,
    }


@respx.mock
def test_trials_endpoint_accepts_a_combined_phase_bucket():
    respx.get(CT_STUDIES_URL).mock(
        return_value=httpx.Response(
            200, json={"studies": [_study("NCT1", phases=("PHASE1", "PHASE2"))]}
        )
    )

    body = _client().get("/api/trials?query=Alzheimer&phase=Phase+1+%2B+Phase+2").json()

    assert [t["nct_id"] for t in body["trials"]] == ["NCT1"]


@respx.mock
def test_trials_endpoint_returns_no_analytics_when_the_registry_is_down():
    respx.get(CT_STUDIES_URL).mock(return_value=httpx.Response(503))

    body = _client().get("/api/trials?query=Alzheimer").json()

    assert body["analytics"] is None
    assert body["metadata"]["source_reached"] is False


# ---------------------------------------------------------------------------
# POST /api/dossier search modes (spec §6.1)
# ---------------------------------------------------------------------------


def _dossier_client() -> TestClient:
    app = FastAPI()
    app.include_router(dossier_api.router, prefix="/api")
    return TestClient(app)


def _stub_orchestrator(monkeypatch) -> dict:
    """Replace the pipeline so a route test only asserts what it forwards."""
    seen: dict = {}

    async def orchestrate(query, mode=SearchMode.compound):
        seen["query"] = query
        seen["mode"] = mode
        return DossierResponse(query=query, status="success", search_mode=mode)

    monkeypatch.setattr(dossier_api._orchestrator, "orchestrate", orchestrate)
    return seen


def test_the_dossier_route_defaults_to_a_compound_search(monkeypatch):
    seen = _stub_orchestrator(monkeypatch)

    body = _dossier_client().post("/api/dossier", json={"query": "aspirin"}).json()

    assert seen["mode"] is SearchMode.compound
    assert body["search_mode"] == "compound"
    assert body["disease_analytics"] is None


@pytest.mark.parametrize("mode", ["compound", "disease", "target"])
def test_the_dossier_route_forwards_each_supported_search_mode(monkeypatch, mode):
    seen = _stub_orchestrator(monkeypatch)

    body = _dossier_client().post(
        "/api/dossier", json={"query": "lung cancer", "search_mode": mode}
    ).json()

    assert seen["mode"] is SearchMode(mode)
    assert body["search_mode"] == mode


def test_the_dossier_route_refuses_a_mode_it_does_not_search(monkeypatch):
    _stub_orchestrator(monkeypatch)

    response = _dossier_client().post(
        "/api/dossier", json={"query": "Novartis", "search_mode": "company"}
    )

    assert response.status_code == 422
