"""Tests for the data-only dossier used when AI synthesis is unavailable."""

from __future__ import annotations

import json

import pytest

from models.schemas import (
    ClinicalTrial,
    CompoundProfile,
    EvidenceItem,
    EvidenceType,
    SearchMode,
    TargetProfile,
)
from services.dossier_generator import DossierGenerator, build_data_dossier


def _evidence() -> list[EvidenceItem]:
    return [
        EvidenceItem(
            source="PubMed",
            source_type="literature",
            id="12345678",
            title="Randomized trial of drug X",
            year=2023,
            authors=["Smith J"],
            abstract="A trial abstract.",
            url="https://pubmed.ncbi.nlm.nih.gov/12345678/",
            evidence_type=EvidenceType.clinical,
            metadata={"pmid": "12345678", "doi": None},
        ),
        EvidenceItem(
            source="openFDA",
            source_type="regulatory",
            id="NDA012345",
            title="DrugX — Indications and Usage",
            abstract="DrugX is indicated for condition Y.",
            url="https://api.fda.gov/drug/label.json",
            evidence_type=EvidenceType.regulatory,
            metadata={"section": "indications_and_usage", "section_title": "Indications and Usage"},
        ),
        EvidenceItem(
            source="openFDA",
            source_type="regulatory",
            id="NDA012345",
            title="DrugX — Warnings",
            abstract="Not to be used in patients with bleeding disorders.",
            url="https://api.fda.gov/drug/label.json",
            evidence_type=EvidenceType.regulatory,
            metadata={"section": "warnings", "section_title": "Warnings"},
        ),
    ]


_COMPOUND = CompoundProfile(
    cid="12345",
    name="drug x",
    synonyms=["DrugX"],
    molecular_formula="C10H12N2O",
    molecular_weight="176.22",
    canonical_smiles="CC(=O)Oc1ccccc1C(=O)O",
)

_TRIALS = [
    ClinicalTrial(
        nct_id="NCT00000001",
        title="Phase 2 study of drug X",
        status="Recruiting",
        phase="Phase 2",
        conditions=["Condition Y"],
        interventions=["DrugX"],
        sponsor="Academic Center",
        study_type="Interventional",
        url="https://clinicaltrials.gov/study/NCT00000001",
    )
]

_TARGETS = [
    TargetProfile(
        accession="P12345",
        name="Cyclooxygenase",
        gene="PTGS2",
        organism="Homo sapiens",
        function_summary="Mediates prostaglandin synthesis.",
        subcellular_location="Cell membrane",
        url="https://www.uniprot.org/uniprotkb/P12345",
    )
]


def test_data_dossier_restates_only_fetched_records():
    """Every narrative section must be populated from real data, not left blank."""
    dossier = build_data_dossier(
        "drug x condition y",
        _evidence(),
        _COMPOUND,
        _TRIALS,
        _TARGETS,
        reason="AI synthesis is unavailable.",
    )

    assert dossier.executive_summary.startswith("AI synthesis is unavailable.")
    assert "CID 12345" in dossier.executive_summary
    assert dossier.compound_profile == _COMPOUND
    assert "P12345" in dossier.mechanism
    assert "Cyclooxygenase" in dossier.mechanism
    assert "Condition Y" in dossier.therapeutic_evidence
    assert "indicated for condition Y" in dossier.therapeutic_evidence
    assert "1 distinct study" in dossier.clinical_development
    assert "not evidence of causality" in dossier.safety
    assert "Warnings" in dossier.safety
    assert dossier.literature_summary and "Randomized trial of drug X" in dossier.literature_summary


def test_data_dossier_does_not_restate_the_trial_tables():
    """Phase counts and record lists belong to the trial section's charts and table."""
    dossier = build_data_dossier(
        "q", _evidence(), _COMPOUND, _TRIALS, _TARGETS, reason="unavailable"
    )

    assert "Phase 2" not in dossier.therapeutic_evidence
    assert "Phase 2" not in dossier.clinical_development
    assert "NCT00000001" not in dossier.clinical_development
    assert "Cell membrane" not in dossier.mechanism


def test_data_dossier_never_invents_hypotheses():
    """Research opportunities are model output only; the fallback must leave them empty."""
    dossier = build_data_dossier(
        "q", _evidence(), _COMPOUND, _TRIALS, _TARGETS, reason="unavailable"
    )
    assert dossier.research_opportunities is None


def test_data_dossier_reports_missing_sources_as_gaps():
    """Absent evidence has to surface as an explicit gap, not silence."""
    dossier = build_data_dossier("q", [], None, [], [], reason="unavailable")

    assert dossier.evidence_gaps
    for expected in ["ClinicalTrials.gov", "openFDA", "UniProt", "literature"]:
        assert expected in dossier.evidence_gaps
    assert "None of the queried sources returned records." in dossier.executive_summary
    assert dossier.references == []


def test_a_skipped_source_is_reported_as_skipped_not_as_a_missing_label():
    """A disease query never consults openFDA, so that must not read as an empty result."""
    dossier = build_data_dossier(
        "lung cancer",
        [],
        None,
        _TRIALS,
        _TARGETS,
        reason="unavailable",
        search_mode=SearchMode.disease,
    )

    assert "No openFDA drug label matched" not in dossier.evidence_gaps
    assert "a disease query names no product" in dossier.evidence_gaps


def test_references_carry_source_identifiers():
    """Identifiers must be labelled so the frontend can link each one out."""
    refs = build_data_dossier(
        "q", _evidence(), _COMPOUND, _TRIALS, _TARGETS, reason="unavailable"
    ).references
    joined = "\n".join(refs)
    assert "PMID: 12345678" in joined
    assert "NCT00000001" in joined
    assert "CID: 12345" in joined
    assert "UniProt. P12345" in joined


@pytest.mark.asyncio
async def test_generate_falls_back_without_api_key(monkeypatch):
    """A missing key degrades to the data dossier instead of raising."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "")
    result = await DossierGenerator().generate(
        query="drug x",
        evidence=_evidence(),
        compound=_COMPOUND,
        trials=_TRIALS,
        targets=_TARGETS,
    )

    assert result.synthesized is False
    assert "OPENROUTER_API_KEY" in result.detail
    assert result.dossier.compound_profile == _COMPOUND
    assert result.dossier.executive_summary


@pytest.mark.asyncio
async def test_generate_falls_back_when_openrouter_errors(monkeypatch):
    """A transport failure on the LLM call must not destroy the dossier."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key-not-real")
    generator = DossierGenerator()

    async def boom(_message):
        from services.dossier_generator import DossierGenerationError

        raise DossierGenerationError("AI synthesis is unavailable (HTTP 503).")

    monkeypatch.setattr(generator, "_call_openrouter", boom)
    result = await generator.generate(
        query="drug x",
        evidence=_evidence(),
        compound=_COMPOUND,
        trials=_TRIALS,
        targets=_TARGETS,
    )

    assert result.synthesized is False
    assert "HTTP 503" in result.detail
    assert result.dossier.mechanism


@pytest.mark.asyncio
async def test_generate_falls_back_when_model_output_unparseable(monkeypatch):
    """Malformed model JSON is reported, and the raw data dossier is still returned."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key-not-real")
    generator = DossierGenerator()

    async def garbage(_message):
        return "this is definitely not json"

    monkeypatch.setattr(generator, "_call_openrouter", garbage)
    result = await generator.generate(
        query="drug x",
        evidence=_evidence(),
        compound=_COMPOUND,
        trials=_TRIALS,
        targets=_TARGETS,
    )

    assert result.synthesized is False
    assert "could not be parsed" in result.detail
    assert result.dossier.compound_profile == _COMPOUND


# ---------------------------------------------------------------------------
# Model output shape tolerance
# ---------------------------------------------------------------------------

def _minimal_payload(**overrides):
    payload = {
        "query": "drug x",
        "executive_summary": "A summary.",
        "mechanism": "Blocks target A.",
        "therapeutic_evidence": "Moderate evidence.",
        "literature_summary": "Small literature base.",
        "clinical_development": "One phase 2 trial.",
        "safety": "Generally tolerated.",
        "evidence_gaps": "No head-to-head trials.",
        "research_opportunities": "HYPOTHESIS: Test combination therapy.",
        "references": ["Smith J (2023). Randomized trial of drug X. PubMed. PMID: 12345678"],
    }
    payload.update(overrides)
    return json.dumps(payload)


def test_parse_dossier_accepts_list_valued_narrative_fields():
    """Models often return narrative fields as lists of points, which is valid output."""
    raw = _minimal_payload(
        research_opportunities=[
            "HYPOTHESIS: First idea with downstream consequences.",
            "HYPOTHESIS: Second idea.",
        ],
        evidence_gaps=["No paediatric data", "Short follow-up"],
    )

    dossier = DossierGenerator._parse_dossier(raw, "drug x")

    assert dossier is not None
    assert "HYPOTHESIS: First idea" in dossier.research_opportunities
    assert "HYPOTHESIS: Second idea" in dossier.research_opportunities
    assert dossier.evidence_gaps == "- No paediatric data\n- Short follow-up"


def test_parse_dossier_drops_malformed_compound_profile():
    """A non-object compound_profile is discarded rather than failing the parse."""
    dossier = DossierGenerator._parse_dossier(
        _minimal_payload(compound_profile="C10H12N2O"), "drug x"
    )

    assert dossier is not None
    assert dossier.compound_profile is None


def test_parse_dossier_coerces_reference_entries():
    """Reference items returned as objects are flattened to strings."""
    dossier = DossierGenerator._parse_dossier(
        _minimal_payload(references=[{"citation": "Smith J (2023). Title."}, "Plain string ref"]),
        "drug x",
    )

    assert dossier is not None
    assert dossier.references == ["Smith J (2023). Title.", "Plain string ref"]


@pytest.mark.asyncio
async def test_list_valued_fields_do_not_trigger_a_repair_call(monkeypatch):
    """Repair round-trips cost a full extra generation; shape variance must not cause one."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key-not-real")
    generator = DossierGenerator()
    calls = []

    async def one_call(_message):
        calls.append(1)
        return _minimal_payload(evidence_gaps=["Gap one", "Gap two"])

    monkeypatch.setattr(generator, "_call_openrouter", one_call)
    result = await generator.generate(
        query="drug x", evidence=_evidence(), compound=_COMPOUND,
        trials=_TRIALS, targets=_TARGETS,
    )

    assert len(calls) == 1
    assert result.synthesized is True


@pytest.mark.asyncio
async def test_call_openrouter_flags_truncated_output(monkeypatch):
    """A reply cut off at the token limit cannot be repaired, so it must fail fast."""
    import httpx
    import respx

    from services.dossier_generator import (
        _OPENROUTER_URL,
        DossierGenerationError,
    )

    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key-not-real")
    generator = DossierGenerator()
    body = {
        "choices": [
            {"finish_reason": "length", "message": {"role": "assistant", "content": '{"q":'}}
        ]
    }

    with respx.mock:
        respx.post(_OPENROUTER_URL).mock(return_value=httpx.Response(200, json=body))
        with pytest.raises(DossierGenerationError, match="cut off"):
            await generator._call_openrouter("anything")


def test_evidence_payload_condenses_long_abstracts():
    """Full abstracts dominate the prompt and slow generation; they are shortened."""
    long_abstract = "Sentence one here. " * 200
    evidence = [
        EvidenceItem(
            source="PubMed",
            source_type="literature",
            id="1",
            title="Long abstract paper",
            authors=[],
            abstract=long_abstract,
            evidence_type=EvidenceType.literature_review,
        )
    ]

    payload = json.loads(
        DossierGenerator()._build_evidence_payload(evidence, None, [], [])
    )

    sent = payload["evidence_items"][0]["abstract"]
    assert len(sent) < len(long_abstract)
    assert sent.endswith("Sentence one here.") or sent.endswith("…")
