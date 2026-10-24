"""Research orchestrator — coordinates all data sources and generates the dossier."""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

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
    CandidateAnalytics,
    ClinicalTrial,
    CompoundProfile,
    DiseaseAnalytics,
    DiseaseConcept,
    Dossier,
    DossierResponse,
    EvidenceItem,
    LiteratureView,
    SearchMode,
    SourceStatus,
    TargetProfile,
    TrialAnalytics,
    TrialRetrievalMetadata,
)
from services.candidate_analytics import compute_candidates
from services.disease_analytics import compute_disease_analytics
from services.dossier_generator import DossierGenerator
from services.evidence_normalizer import deduplicate, normalize_evidence_list
from services.evidence_strength import compute_evidence_strength
from services.literature_view import build_view
from services.trial_analytics import compute_analytics

logger = logging.getLogger(__name__)

# PubChem resolves a compound by name and openFDA matches labels on brand or
# generic product name. Neither answers a disease or a gene query, so for those
# search modes they are recorded as skipped rather than queried and reported
# back as an empty result.
_PRODUCT_LOOKUP_ONLY = {
    "PubChem": "PubChem resolves a compound by name; a {mode} query names no product.",
    "openFDA": "openFDA matches labels by brand or generic name; a {mode} query names no product.",
}

_SKIP_REASON = {
    SearchMode.disease: "disease",
    SearchMode.target: "target",
}


class ResearchOrchestrator:
    """Coordinates all scientific data sources and calls the dossier generator."""

    def __init__(self) -> None:
        self._generator = DossierGenerator()

    async def orchestrate(
        self, query: str, mode: SearchMode = SearchMode.compound
    ) -> DossierResponse:
        """Run the research pipeline for one search mode and return a DossierResponse."""

        product_lookup = mode is SearchMode.compound
        tasks: dict[str, object] = {
            "PubMed": pubmed.search_literature(query),
            "EuropePMC": europepmc.search_literature(query),
            "ClinicalTrials.gov": clinicaltrials.fetch_trials(query),
            "UniProt": uniprot.search_target(query),
        }
        if product_lookup:
            tasks["PubChem"] = pubchem.search_compound(query)
            tasks["openFDA"] = openfda.search_drug_labels(query)
        else:
            tasks["DiseaseOntology"] = disease_ontology.lookup_disease(query)

        # Sources are queried in parallel with per-source exception isolation.
        results = await asyncio.gather(*tasks.values(), return_exceptions=True)
        by_source = dict(zip(tasks.keys(), results))

        compound: Optional[CompoundProfile] = None
        all_evidence: list[EvidenceItem] = []
        all_trials: list[ClinicalTrial] = []
        all_targets: list[TargetProfile] = []
        fda_items: list[EvidenceItem] = []
        concept: Optional[DiseaseConcept] = None

        # PubChem — a compound-name lookup, so only run for a compound query.
        if product_lookup:
            compound, ss = _handle_compound_result(
                "PubChem", by_source["PubChem"]
            )
            source_statuses: list[SourceStatus] = [ss]
        else:
            source_statuses = [
                _skipped_status("PubChem", _skip_reason("PubChem", mode))
            ]

        # PubMed
        pubmed_items, ss = _handle_evidence_list(
            "PubMed", by_source["PubMed"]
        )
        all_evidence.extend(pubmed_items)
        source_statuses.append(ss)

        # EuropePMC
        epmc_items, ss = _handle_evidence_list(
            "EuropePMC", by_source["EuropePMC"]
        )
        all_evidence.extend(epmc_items)
        source_statuses.append(ss)

        # ClinicalTrials
        trials, trial_metadata, trials_status = _handle_trials_result(
            "ClinicalTrials.gov", query, by_source["ClinicalTrials.gov"]
        )
        all_trials.extend(trials)
        source_statuses.append(trials_status)

        # openFDA
        if product_lookup:
            fda_items, ss = _handle_evidence_list(
                "openFDA", by_source["openFDA"]
            )
            all_evidence.extend(fda_items)
            source_statuses.append(ss)
        else:
            source_statuses.append(
                _skipped_status("openFDA", _skip_reason("openFDA", mode))
            )

        # UniProt
        targets, ss = _handle_targets_result("UniProt", by_source["UniProt"])
        all_targets.extend(targets)
        source_statuses.append(ss)

        # Disease concept lookup — only asked for a disease query.
        if not product_lookup:
            concept, ss = _handle_concept_result(
                by_source.get("DiseaseOntology"), query
            )
            source_statuses.append(ss)

        # Step 3: Normalize, deduplicate, and order the literature
        normalized = normalize_evidence_list(all_evidence)
        deduped = deduplicate(normalized)
        # The merge counts describe publications, so they are recovered from the
        # publications' own provenance rather than from every record retrieved:
        # a regulatory passage is not a publication that was merged.
        literature_result = build_view(deduped, query, LiteratureView.most_relevant)
        ranked = literature_result.items + [
            item for item in deduped if item.source_type != "literature"
        ]
        # The ordered records are the literature subset of `ranked`, so the
        # metadata is sent without them; a different view or filter is asked for
        # at /api/literature/views.
        literature_meta = literature_result.model_copy(update={"items": []})

        # Deterministic aggregates for the dashboard. The model is not asked to
        # count anything. When the registry could not be consulted the
        # analytics are omitted entirely rather than rendered as zero-filled
        # charts, which would read as "no trials exist".
        trial_analytics: Optional[TrialAnalytics] = None
        candidate_analytics: Optional[CandidateAnalytics] = None
        if trial_metadata.source_reached:
            trial_analytics = compute_analytics(all_trials, trial_metadata)
            candidate_analytics = compute_candidates(
                all_trials, trial_metadata, fda_items
            )
        evidence_strength = compute_evidence_strength(ranked)

        # Disease view for a disease query only: a compound query resolves to one
        # product, so there is no subtype to separate.
        disease_analytics: Optional[DiseaseAnalytics] = None
        if mode is SearchMode.disease:
            disease_analytics = compute_disease_analytics(
                query=query,
                concept=concept,
                trials=all_trials,
                evidence=ranked,
                candidates=candidate_analytics,
                targets=all_targets,
                metadata=trial_metadata,
            )

        # Step 4: Generate dossier. A missing or failing LLM degrades to a
        # data-only dossier rather than blanking the whole page.
        dossier: Optional[Dossier] = None
        synthesized = False
        synthesis_detail: Optional[str] = None
        try:
            result = await self._generator.generate(
                query=query,
                evidence=ranked,
                compound=compound,
                trials=all_trials,
                targets=all_targets,
                search_mode=mode,
            )
            dossier = result.dossier
            synthesized = result.synthesized
            synthesis_detail = result.detail
        except Exception as exc:  # noqa: BLE001
            logger.exception("Dossier generation failed unexpectedly")
            synthesis_detail = f"Dossier generation failed: {exc}"

        # A source MolTel did not query for this search mode is not a failure, so
        # it cannot make the retrieval partial.
        queried = [s for s in source_statuses if s.status != "skipped"]
        all_sources_returned_data = all(s.status == "success" for s in queried)
        if dossier is None:
            overall_status = "error"
        elif synthesized and all_sources_returned_data:
            overall_status = "success"
        else:
            overall_status = "partial"

        # Attach source statuses to dossier if available
        if dossier is not None:
            dossier = dossier.model_copy(update={"sources_status": source_statuses})

        # Step 5: Return DossierResponse (include raw structured data for frontend tables)
        return DossierResponse(
            query=query,
            status=overall_status,
            search_mode=mode,
            sources=source_statuses,
            dossier=dossier,
            ai_synthesized=synthesized,
            synthesis_detail=synthesis_detail,
            evidence_items=ranked,
            clinical_trials=all_trials,
            targets=all_targets,
            evidence_strength=evidence_strength,
            trial_analytics=trial_analytics,
            candidate_analytics=candidate_analytics,
            disease_analytics=disease_analytics,
            literature=literature_meta,
            retrieved_at=trial_metadata.retrieved_at,
        )


# ---- Helper functions for result unpacking ----

def _skip_reason(source_name: str, mode: SearchMode) -> str:
    return _PRODUCT_LOOKUP_ONLY[source_name].format(mode=_SKIP_REASON[mode])


def _skipped_status(source_name: str, reason: str) -> SourceStatus:
    """Record a source MolTel deliberately did not query.

    Reported as skipped with its reason, so the panel never reads as a source
    failure or as an empty result set.
    """
    return SourceStatus(source_name=source_name, status="skipped", count=0, note=reason)


def _handle_concept_result(
    result: DiseaseConcept | BaseException | None, query: str
) -> tuple[Optional[DiseaseConcept], SourceStatus]:
    """Unpack the disease ontology lookup.

    A concept lookup that ran and found nothing is reported as no_results: the
    dashboard then uses the condition strings the records themselves carry.
    """
    if isinstance(result, BaseException):
        logger.warning("Disease concept lookup failed: %s", result)
        return None, SourceStatus(
            source_name="Disease concept",
            status="error",
            count=0,
            error_message=str(result),
        )
    if result is None:
        return None, SourceStatus(
            source_name="Disease concept",
            status="error",
            count=0,
            error_message="The disease concept lookup returned nothing at all.",
        )
    if result.canonical is not None:
        return result, SourceStatus(
            source_name="Disease concept",
            status="success",
            count=1 + len(result.related),
            note=result.note,
        )
    return result, SourceStatus(
        source_name="Disease concept",
        status="no_results" if result.source_reached else "error",
        count=0,
        error_message=None if result.source_reached else result.note,
        note=result.note,
    )


def _handle_compound_result(
    source_name: str, result: CompoundProfile | BaseException | None
) -> tuple[Optional[CompoundProfile], SourceStatus]:
    if isinstance(result, BaseException):
        logger.warning("%s failed: %s", source_name, result)
        return None, SourceStatus(
            source_name=source_name, status="error", count=0,
            error_message=str(result)
        )
    if result is None:
        return None, SourceStatus(source_name=source_name, status="no_results", count=0)
    return result, SourceStatus(source_name=source_name, status="success", count=1)


def _handle_evidence_list(
    source_name: str, result: list[EvidenceItem] | BaseException | None
) -> tuple[list[EvidenceItem], SourceStatus]:
    if isinstance(result, BaseException):
        logger.warning("%s failed: %s", source_name, result)
        return [], SourceStatus(
            source_name=source_name, status="error", count=0,
            error_message=str(result)
        )
    if not result:
        return [], SourceStatus(source_name=source_name, status="no_results", count=0)
    return result, SourceStatus(source_name=source_name, status="success", count=len(result))


def _handle_trials_result(
    source_name: str,
    query: str,
    result: tuple[list[ClinicalTrial], TrialRetrievalMetadata] | BaseException | None,
) -> tuple[list[ClinicalTrial], TrialRetrievalMetadata, SourceStatus]:
    if isinstance(result, BaseException):
        logger.warning("%s failed: %s", source_name, result)
        return (
            [],
            TrialRetrievalMetadata(
                query=query,
                source_reached=False,
                partial=True,
                note=f"{source_name} could not be consulted.",
            ),
            SourceStatus(
                source_name=source_name, status="error", count=0,
                error_message=str(result)
            ),
        )
    trials, metadata = result if result else (
        [],
        TrialRetrievalMetadata(query=query, source_reached=False, partial=True),
    )
    if not trials and not metadata.source_reached:
        # An unreachable registry is reported as an error, not as "no trials
        # exist for this topic".
        return trials, metadata, SourceStatus(
            source_name=source_name,
            status="error",
            count=0,
            error_message=metadata.note or "Source could not be consulted.",
        )
    if not trials:
        return trials, metadata, SourceStatus(
            source_name=source_name, status="no_results", count=0
        )
    return trials, metadata, SourceStatus(
        source_name=source_name, status="success", count=len(trials)
    )


def _handle_targets_result(
    source_name: str, result: list[TargetProfile] | BaseException | None
) -> tuple[list[TargetProfile], SourceStatus]:
    if isinstance(result, BaseException):
        logger.warning("%s failed: %s", source_name, result)
        return [], SourceStatus(
            source_name=source_name, status="error", count=0,
            error_message=str(result)
        )
    if not result:
        return [], SourceStatus(source_name=source_name, status="no_results", count=0)
    return result, SourceStatus(source_name=source_name, status="success", count=len(result))
