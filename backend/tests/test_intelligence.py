"""Evidence strength and AI research-intelligence parsing tests.

The OpenRouter calls in these tests are served by respx with hand-written
payloads, so no test contacts the model or spends credits.
"""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from models.schemas import EvidenceItem, EvidenceType
from services.dossier_generator import (
    NO_CONTRADICTION_ASSESSMENT,
    DossierGenerator,
    build_data_dossier,
)
from services.evidence_strength import compute_evidence_strength

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


def _item(ident, title, evidence_type):
    return EvidenceItem(
        source="PubMed",
        source_type="literature",
        id=ident,
        title=title,
        url=f"https://example.org/{ident}",
        evidence_type=evidence_type,
        metadata={"pmid": ident},
    )


# ---------------------------------------------------------------------------
# Evidence strength — deterministic, no model
# ---------------------------------------------------------------------------


def test_evidence_strength_groups_records_into_classes():
    strength = compute_evidence_strength(
        [
            _item("1", "Randomized controlled trial of X", EvidenceType.randomized_controlled_trial),
            _item("2", "Trial of X without stated randomization", EvidenceType.clinical),
            _item("3", "Cohort of exposed workers", EvidenceType.observational),
            _item("4", "Knockout mouse study", EvidenceType.animal),
            _item("5", "Receptor binding assay", EvidenceType.biochemical),
            _item("6", "Docking simulation", EvidenceType.computational),
            _item("7", "Narrative review", EvidenceType.literature_review),
            _item("8", "Editorial on X", EvidenceType.editorial),
            _item("9", "Erratum to a trial of X", EvidenceType.correction_or_retraction),
            _item("10", "Case report of X", EvidenceType.case_report),
            _item("11", "Paper with no design in its metadata", EvidenceType.other),
        ]
    )

    keys = [c.key for c in strength.categories]
    assert keys == [
        "rct",
        "clinical_trial",
        "observational",
        "case_report",
        "animal",
        "cellular",
        "computational",
        "review",
        "editorial",
        "correction_or_retraction",
        "unclassified",
    ]
    assert [c.count for c in strength.categories] == [1] * 11
    assert strength.unclassified_count == 1
    # Biochemical and cellular experiments share the in vitro class.
    assert any(
        r.startswith("Receptor binding assay [5]") for r in strength.categories[5].records
    )
    # Every class states the rule that placed records in it.
    assert all(c.criteria for c in strength.categories)
    # The record label carries what the source reported, not our interpretation.
    assert "source type: no publication type reported" in strength.categories[0].records[0]


def test_evidence_strength_keeps_registry_trials_out_of_the_literature_tally():
    """Counting a registry trial here and in the trial section would double-count it."""
    strength = compute_evidence_strength([_item("1", "Label text", EvidenceType.regulatory)])

    assert [c.key for c in strength.categories] == ["regulatory"]
    assert any("Clinical Development" in l for l in strength.limitations)


def test_evidence_strength_reports_no_numeric_score():
    """The spec forbids presenting an arbitrary score as a scientific measure."""
    strength = compute_evidence_strength([_item("1", "Trial", EvidenceType.clinical)])

    assert not hasattr(strength, "score")
    assert strength.predominant_tier == "clinical_trial"
    assert strength.automated is True
    assert "how reliable or conclusive they are" in strength.interpretation


def test_evidence_strength_flags_absent_human_evidence():
    strength = compute_evidence_strength(
        [
            _item("1", "Cell line experiment", EvidenceType.cellular),
            _item("2", "In silico screen", EvidenceType.computational),
        ]
    )

    assert strength.predominant_tier == "cellular"
    assert any("no classified human study" in lim.lower() for lim in strength.limitations)


def test_empty_evidence_yields_no_categories_and_no_claim_of_strength():
    strength = compute_evidence_strength([])

    assert strength.categories == []
    assert strength.predominant_tier is None
    assert "publication-type metadata" in strength.interpretation


# ---------------------------------------------------------------------------
# Contradictions and gaps from the single synthesis call
# ---------------------------------------------------------------------------


_BASE_DOSSIER = {
    "query": "clemizole and TRPC5 in Alzheimer's disease",
    "executive_summary": "Two records describe TRPC5 blockade in mouse models.",
    "mechanism": None,
    "therapeutic_evidence": None,
    "literature_summary": "Two records.",
    "clinical_development": "No clinical trial data available",
    "safety": "No safety data available",
    "evidence_gaps": "Only preclinical records.",
    "research_opportunities": "HYPOTHESIS: test in a second model.",
    "references": ["Author (2024). Title. PubMed. PMID: 111"],
}


async def _generate_with(payload: dict, monkeypatch):
    """Run one synthesis call against a mocked OpenRouter response."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    generator = DossierGenerator()
    with respx.mock:
        respx.post(OPENROUTER_URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {"content": json.dumps(payload)},
                            "finish_reason": "stop",
                        }
                    ]
                },
            )
        )
        return await generator.generate(
            query=payload["query"],
            evidence=[_item("111", "Study", EvidenceType.animal)],
            compound=None,
            trials=[],
            targets=[],
        )


@pytest.mark.asyncio
async def test_supported_contradiction_is_kept_with_its_citations(monkeypatch):
    payload = {
        **_BASE_DOSSIER,
        "contradictory_findings": {
            "assessment": "potentially_conflicting",
            "insufficient_evidence": False,
            "contradictions": [
                {
                    "claim": "Does TRPC5 inhibition improve memory?",
                    "study_a": "PMID 111 reports improved maze performance.",
                    "study_b": "PMID 222 reports no effect.",
                    "context_difference": "Different age of onset.",
                    "possible_explanation": None,
                    "classification": "potentially_conflicting",
                    "confidence": "low",
                    "missing_information": "No shared endpoint.",
                    "citations": ["PMID: 111", "PMID: 222"],
                },
                # No citations: an unsupported claim, so it is dropped.
                {"claim": "Uncited assertion", "citations": []},
            ],
        },
    }

    result = await _generate_with(payload, monkeypatch)

    findings = result.dossier.contradictory_findings
    assert result.synthesized is True
    assert len(findings.contradictions) == 1
    assert findings.contradictions[0].claim.startswith("Does TRPC5")
    assert findings.contradictions[0].citations == ["PMID: 111", "PMID: 222"]
    # Readers get the phrase, not the registry-style code.
    assert findings.assessment == "Potentially conflicting findings"


@pytest.mark.asyncio
async def test_absent_contradiction_section_uses_the_required_honest_wording(monkeypatch):
    payload = {**_BASE_DOSSIER, "contradictory_findings": {"contradictions": []}}

    result = await _generate_with(payload, monkeypatch)

    findings = result.dossier.contradictory_findings
    assert findings.contradictions == []
    assert findings.assessment == NO_CONTRADICTION_ASSESSMENT
    assert "does not establish" in findings.assessment


@pytest.mark.asyncio
async def test_malformed_intelligence_sections_do_not_void_the_dossier(monkeypatch):
    payload = {
        **_BASE_DOSSIER,
        "contradictory_findings": "the model returned a sentence, not an object",
        "research_gap_analysis": [{"question": "Which dose translates?"}, "Bare string gap"],
    }

    result = await _generate_with(payload, monkeypatch)

    assert result.synthesized is True
    # An unstructured contradiction block is reported as not assessed, which is
    # a different claim from "assessed and found consistent".
    assessment = result.dossier.contradictory_findings.assessment
    assert "not assessed" in assessment.lower()
    assert result.dossier.contradictory_findings.contradictions == []
    # Models sometimes return gaps as a plain list of questions; both forms are
    # accepted rather than dropping the section.
    assert [g.question for g in result.dossier.research_gap_analysis] == [
        "Which dose translates?",
        "Bare string gap",
    ]


@pytest.mark.asyncio
async def test_gap_list_is_capped_and_keeps_its_labels(monkeypatch):
    payload = {
        **_BASE_DOSSIER,
        "research_gap_analysis": [
            {
                "question": f"Gap {i}",
                "label": "Potential research gap",
                "references": [f"PMID: 11{i}"],
            }
            for i in range(9)
        ],
    }

    result = await _generate_with(payload, monkeypatch)

    gaps = result.dossier.research_gap_analysis
    assert len(gaps) == 4
    assert gaps[0].label == "Potential research gap"
    assert gaps[0].references == ["PMID: 110"]


# ---------------------------------------------------------------------------
# Data-only fallback stays honest about what it cannot do
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_agreement_is_not_listed_as_a_contradiction(monkeypatch):
    """A record pair the model itself calls consistent is not a conflict.

    Live output showed the model filing "no direct contradiction here" as a
    contradiction entry, which would put a finding on the page that the records
    do not support.
    """
    payload = {
        **_BASE_DOSSIER,
        "contradictory_findings": {
            "assessment": "different_experimental_contexts",
            "contradictions": [
                {
                    "claim": "Tirzepatide vs semaglutide weight loss",
                    "study_a": "PMID 111 reports superior reduction.",
                    "study_b": "PMID 222 reports the same direction.",
                    "classification": "generally_consistent",
                    "citations": ["PMID: 111", "PMID: 222"],
                },
                {
                    "claim": "Does target blockade worsen cognition?",
                    "study_a": "PMID 111 reports impairment after blockade.",
                    "study_b": "PMID 333 reports no change.",
                    "classification": "potentially_conflicting",
                    "citations": ["PMID: 111", "PMID: 333"],
                },
            ],
        },
    }

    result = await _generate_with(payload, monkeypatch)

    findings = result.dossier.contradictory_findings
    assert len(findings.contradictions) == 1
    assert findings.contradictions[0].claim.startswith("Does target blockade")
    # The assessment code is turned into the phrase a reader is shown.
    assert findings.assessment == "Different experimental contexts"


def test_data_only_dossier_says_ai_analysis_was_unavailable():
    dossier = build_data_dossier(
        query="telmisartan",
        evidence=[_item("1", "Trial", EvidenceType.clinical)],
        compound=None,
        trials=[],
        targets=[],
        reason="AI synthesis is not configured.",
    )

    assert dossier.research_gap_analysis == []
    assert "requires AI synthesis" in dossier.contradictory_findings.assessment
    # The fallback never manufactures hypotheses.
    assert dossier.research_opportunities is None
