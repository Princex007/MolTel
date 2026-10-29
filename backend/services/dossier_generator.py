"""OpenRouter dossier generation service."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import httpx

from models.schemas import (
    ClinicalTrial,
    CompoundProfile,
    Contradiction,
    ContradictoryFindings,
    Dossier,
    EvidenceItem,
    EvidenceStrength,
    QueryAttributionSummary,
    ResearchGap,
    SearchMode,
    TargetProfile,
    TrialAnalytics,
)
from utils.text import condense, truncate

logger = logging.getLogger(__name__)

# Search modes whose query names no product, so PubChem and openFDA are skipped
# rather than queried. Prose about labelling has to say it was not consulted.
_NOT_A_PRODUCT_QUERY = {SearchMode.disease: "disease", SearchMode.target: "target"}

_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"
_OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
_MAX_EVIDENCE_ITEMS = 30
# Abstracts longer than this are condensed before being sent to the model.
_MAX_ABSTRACT_CHARS = 600
# Bounds generation time; a full dossier with references runs ~3.5k tokens.
_MAX_OUTPUT_TOKENS = 8192
_LLM_TIMEOUT_SECONDS = 90.0


_DOSSIER_TEXT_FIELDS = (
    "executive_summary",
    "mechanism",
    "therapeutic_evidence",
    "literature_summary",
    "clinical_development",
    "safety",
    "evidence_gaps",
    "research_opportunities",
)


def _as_text(value: object) -> Optional[str]:
    """Coerce a model-supplied value to the plain text the schema expects.

    Models frequently return narrative fields as a list of points rather than a
    single string. That is good output, not an error, so it is joined here
    instead of being sent back through a costly repair round-trip.
    """
    if value is None:
        return None
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, list):
        parts = [text for text in (_as_text(item) for item in value) if text]
        if not parts:
            return None
        if len(parts) == 1:
            return parts[0]
        return "\n".join(f"- {part}" for part in parts)
    if isinstance(value, dict):
        parts = [text for text in (_as_text(v) for v in value.values()) if text]
        return "\n".join(parts) or None
    return str(value)


class DossierGenerationError(Exception):
    """Raised when the dossier cannot be generated or parsed."""


# Shown whenever the model produced no supported contradiction, including when
# it failed to return the section at all. Per the research-safety rules this
# deliberately stops short of claiming that conflicting evidence is absent.
NO_CONTRADICTION_ASSESSMENT = (
    "No clear contradiction was identified in the retrieved evidence. This does "
    "not establish that conflicting evidence does not exist."
)


# Classifications that state the records agree, or cannot be compared. An entry
# carrying one of these is not a contradiction, whatever the model filed it as.
_NON_CONFLICT_CLASSIFICATIONS = frozenset(
    {"generally_consistent", "insufficient_evidence_to_compare"}
)

_CLASSIFICATION_LABELS = {
    "generally_consistent": "Generally consistent findings",
    "potentially_conflicting": "Potentially conflicting findings",
    "different_experimental_contexts": "Different experimental contexts",
    "insufficient_evidence_to_compare": "Insufficient evidence to compare",
}


def _classification_key(value: Optional[str]) -> str:
    return (value or "").strip().lower().replace(" ", "_").replace("-", "_")


def _classification_label(value: str) -> str:
    """Turn a classification code into the phrase the reader sees."""
    return _CLASSIFICATION_LABELS.get(_classification_key(value), value)


def _parse_contradictions(value: object) -> ContradictoryFindings:
    """Validate the model's contradiction block, degrading rather than failing.

    A malformed section costs the reader one panel, not the whole dossier, so
    unusable entries are dropped and the remaining ones kept.
    """
    if isinstance(value, list):
        value = {"contradictions": value}
    if not isinstance(value, dict):
        # Nothing structured to work with: report that the comparison did not
        # happen rather than that it happened and found nothing.
        return ContradictoryFindings(
            contradictions=[],
            assessment=(
                "The synthesis did not return a structured contradiction "
                "analysis, so this was not assessed."
            ),
            insufficient_evidence=True,
        )

    raw_items = value.get("contradictions")
    if not isinstance(raw_items, list):
        raw_items = []

    contradictions: list[Contradiction] = []
    for entry in raw_items[:3]:
        if not isinstance(entry, dict):
            continue
        # Unwrap a {"contradiction": {...}} nesting some models add.
        entry = entry.get("contradiction") or entry
        if not isinstance(entry, dict):
            continue
        citations = entry.get("citations")
        classification = _as_text(entry.get("classification"))
        parsed = Contradiction(
            **{
                field: _as_text(entry.get(field))
                for field in (
                    "claim", "study_a", "study_b", "context_difference",
                    "possible_explanation", "confidence", "missing_information",
                )
            },
            classification=classification,
            citations=[t for t in (_as_text(c) for c in (citations or [])) if t],
        )
        # A contradiction with no cited record is an unsupported claim, and one
        # the model itself classifies as agreement or incomparable is not a
        # conflict at all — listing either would put a finding on the page that
        # the record set does not support.
        if not (parsed.claim and parsed.citations):
            continue
        if _classification_key(classification) in _NON_CONFLICT_CLASSIFICATIONS:
            continue
        contradictions.append(parsed)

    assessment = _as_text(value.get("assessment"))
    if not contradictions:
        assessment = NO_CONTRADICTION_ASSESSMENT
    elif assessment:
        assessment = _classification_label(assessment)

    return ContradictoryFindings(
        contradictions=contradictions,
        assessment=assessment,
        insufficient_evidence=bool(
            value.get("insufficient_evidence", not contradictions)
        ),
    )


def _parse_research_gaps(value: object) -> list[ResearchGap]:
    """Validate the model's gap list, dropping entries with no supporting record."""
    if isinstance(value, dict):
        value = value.get("gaps") or value.get("research_gaps") or list(value.values())
    if not isinstance(value, list):
        return []

    gaps: list[ResearchGap] = []
    for entry in value[:4]:
        if isinstance(entry, str):
            entry = {"question": entry}
        if not isinstance(entry, dict):
            continue
        refs = entry.get("references")
        parsed = ResearchGap(
            **{
                field: _as_text(entry.get(field))
                for field in (
                    "question", "current_evidence", "uncertainty",
                    "why_it_matters", "next_step", "confidence", "label",
                )
            },
            references=[t for t in (_as_text(r) for r in (refs or [])) if t],
        )
        if parsed.question:
            gaps.append(parsed)
    return gaps


@dataclass(frozen=True)
class DossierResult:
    """A dossier plus whether the model actually synthesised it."""

    dossier: Dossier
    synthesized: bool
    detail: Optional[str] = None


def build_data_dossier(
    query: str,
    evidence: list[EvidenceItem],
    compound: Optional[CompoundProfile],
    trials: list[ClinicalTrial],
    targets: list[TargetProfile],
    reason: str,
    search_mode: SearchMode = SearchMode.compound,
) -> Dossier:
    """Assemble a dossier straight from retrieved records, without the LLM.

    Used when AI synthesis is unavailable so the dossier still shows the real
    source data instead of an empty page. Nothing here is inferred: every
    sentence restates a record that was actually fetched. ``search_mode`` keeps
    the wording honest about sources this mode never consulted.
    """
    literature = [e for e in evidence if e.source_type == "literature"]
    regulatory = [e for e in evidence if e.source_type == "regulatory"]

    def _count_by(items: list[EvidenceItem]) -> str:
        counts: dict[str, int] = {}
        for item in items:
            counts[item.source] = counts.get(item.source, 0) + 1
        return ", ".join(f"{n} from {s}" for s, n in sorted(counts.items()))

    def _n(count: int, singular: str, plural: str) -> str:
        return f"{count} {singular if count == 1 else plural}"

    summary_parts = [reason]
    if compound:
        identity = f"PubChem records {compound.name or query}"
        if compound.cid:
            identity += f" (CID {compound.cid})"
        if compound.molecular_formula:
            identity += f", formula {compound.molecular_formula}"
        summary_parts.append(identity + ".")
    summary_parts.append(
        "Retrieved "
        + _n(len(literature), "literature record", "literature records")
        + (f" ({_count_by(literature)})" if literature else "")
        + ", "
        + _n(len(trials), "clinical trial", "clinical trials")
        + ", "
        + _n(len(regulatory), "regulatory label section", "regulatory label sections")
        + ", and "
        + _n(len(targets), "protein target", "protein targets")
        + "."
    )
    if not (literature or trials or regulatory or targets or compound):
        summary_parts.append("None of the queried sources returned records.")

    mechanism: Optional[str] = None
    if targets:
        # The target table carries accession, gene, function and location, so the
        # prose names the records instead of restating their fields.
        names = ", ".join(
            (t.name or t.accession)
            + f" ({', '.join(x for x in (t.gene, t.accession) if x)})"
            for t in targets[:8]
        )
        more = "" if len(targets) <= 8 else f", and {len(targets) - 8} more"
        mechanism = (
            f"UniProt returned {len(targets)} {'target record' if len(targets) == 1 else 'target records'} "
            f"for this query: {names}{more}. Their functions, subcellular locations and "
            "accessions are listed with source links in the target table."
        )

    therapeutic_parts: list[str] = []
    if trials:
        conditions = sorted({c for t in trials for c in t.conditions if c})[:12]
        if conditions:
            therapeutic_parts.append(
                "Condition terms reported by the retrieved studies: "
                + ", ".join(conditions)
                + "."
            )
        else:
            therapeutic_parts.append(
                f"{len(trials)} registered studies were retrieved; none reported a condition term."
            )
    indications = [e for e in regulatory if e.metadata.get("section") == "indications_and_usage"]
    if indications:
        therapeutic_parts.append(
            "Approved labelling states: "
            + " ".join(condense(e.abstract or "", 300) for e in indications[:2])
        )
    if not therapeutic_parts:
        if search_mode in _NOT_A_PRODUCT_QUERY:
            therapeutic_parts.append(
                "No registered trials were returned for this query, and no drug label "
                f"was consulted — a {_NOT_A_PRODUCT_QUERY[search_mode]} query names no product."
            )
        else:
            therapeutic_parts.append(
                "No registered trials and no approved label indications were returned for this query."
            )

    literature_summary: Optional[str] = None
    if literature:
        years = sorted(e.year for e in literature if e.year)
        missing = len(literature) - len(years)
        if not years:
            span = "no record reported a publication year"
        elif years[0] == years[-1]:
            span = f"all dated {years[0]}"
        else:
            span = f"dated {years[0]}–{years[-1]}"
        tail = f" ({missing} with no year in the source record)" if missing else ""
        top = "; ".join(
            truncate(e.title or "Untitled", 120) for e in literature[:5]
        )
        literature_summary = (
            f"{len(literature)} records, {span}{tail}. Highest-ranked of the records "
            f"retrieved — not a claim about the whole literature: {top}."
        )

    clinical_development: Optional[str] = None
    if trials:
        # The record table is the authoritative list and the charts carry the
        # counts, so restating every row here duplicated both.
        noun = "study" if len(trials) == 1 else "studies"
        clinical_development = (
            f"ClinicalTrials.gov returned {len(trials)} distinct {noun} for this query. "
            "Each one is listed in the trial records table with its registry phase, "
            "registry status and source link; the counts and charts are computed from "
            "that same deduplicated list."
        )

    safety: Optional[str] = None
    # Several marketed products share near-identical labelling; one excerpt per
    # section keeps the summary readable. The full set stays in the table.
    by_section: dict[str, EvidenceItem] = {}
    for e in regulatory:
        section = str(e.metadata.get("section") or "")
        if section == "indications_and_usage" or not section:
            continue
        by_section.setdefault(section, e)
    if by_section:
        body = "\n".join(
            f"- {e.metadata.get('section_title') or section}: "
            f"{condense(e.abstract or '', 400)}"
            for section, e in by_section.items()
        )
        safety = (
            "Quoted from FDA drug labelling. Adverse reactions listed on a label "
            "are spontaneous reports and are not evidence of causality.\n" + body
        )

    gaps: list[str] = []
    if not trials:
        gaps.append("No ClinicalTrials.gov records were returned for this query.")
    if not regulatory:
        if search_mode in _NOT_A_PRODUCT_QUERY:
            gaps.append(
                "openFDA matches labels by brand or generic name; a "
                f"{_NOT_A_PRODUCT_QUERY[search_mode]} query names no product, so no label "
                "was consulted for this dossier."
            )
        else:
            gaps.append("No openFDA drug label matched this query.")
    if not targets:
        gaps.append("UniProt returned no protein target for this query.")
    if not literature:
        gaps.append("No literature records were returned from PubMed or Europe PMC.")
    elif len(literature) < 5:
        gaps.append(f"Only {len(literature)} literature records were returned.")
    human_evidence = [
        e
        for e in literature
        if e.evidence_type.value
        in {"clinical", "randomized_controlled_trial", "systematic_review", "observational", "case_report"}
    ]
    if literature and not human_evidence and not trials:
        gaps.append(
            "None of the retrieved literature is classified as clinical; "
            "the evidence base here is preclinical or secondary."
        )

    references = build_references(evidence, compound, trials, targets)

    return Dossier(
        query=query,
        executive_summary=" ".join(summary_parts),
        compound_profile=compound,
        mechanism=mechanism,
        therapeutic_evidence="\n".join(therapeutic_parts),
        literature_summary=literature_summary,
        clinical_development=clinical_development,
        safety=safety,
        evidence_gaps="\n".join(f"- {g}" for g in gaps) if gaps else None,
        # Hypotheses are only ever produced by the model; never invent them here.
        research_opportunities=None,
        # Comparing records for conflict, and judging what is unexplored, are
        # both interpretive tasks. Without the model the panels say so rather
        # than implying the evidence was checked and found clean.
        contradictory_findings=ContradictoryFindings(
            contradictions=[],
            assessment=(
                "Comparative analysis of these records requires AI synthesis, "
                f"which is unavailable: {reason}"
            ),
            insufficient_evidence=True,
        ),
        research_gap_analysis=[],
        references=references,
    )


def build_references(
    evidence: list[EvidenceItem],
    compound: Optional[CompoundProfile],
    trials: list[ClinicalTrial],
    targets: list[TargetProfile],
) -> list[str]:
    """Format one citation string per retrieved record.

    Identifiers are labelled (PMID:, DOI:, NCT…, CID, accession) so the frontend
    can turn each reference into a working link back to its source.
    """
    refs: list[str] = []
    for e in evidence[:_MAX_EVIDENCE_ITEMS]:
        author = e.authors[0] if e.authors else e.source
        year = f" ({e.year})" if e.year else ""
        pmid = e.metadata.get("pmid")
        doi = e.metadata.get("doi")
        identifier = (
            f"PMID: {pmid}" if pmid
            else f"DOI: {doi}" if doi
            else e.id if e.source_type == "regulatory" and e.id
            else f"ID: {e.id} {e.url}".strip() if e.id or e.url
            else ""
        )
        refs.append(
            f"{author}{year}. {e.title or 'Untitled'}. {e.source}. {identifier}".strip()
        )
    for t in trials:
        refs.append(f"{t.title or 'Untitled study'}. ClinicalTrials.gov. {t.nct_id}")
    if compound and compound.cid:
        refs.append(
            f"{compound.name or 'Compound'}. PubChem. CID: {compound.cid}"
        )
    for tgt in targets:
        refs.append(f"{tgt.name or tgt.accession}. UniProt. {tgt.accession}")
    return refs


class DossierGenerator:
    """Generates a structured research dossier via OpenRouter."""

    def __init__(self) -> None:
        self._api_key = os.getenv("OPENROUTER_API_KEY", "")
        self._model = os.getenv("OPENROUTER_MODEL", "openrouter/auto")
        self._system_prompt = self._load_prompt("dossier.txt")

    def _load_prompt(self, filename: str) -> str:
        path = _PROMPTS_DIR / filename
        try:
            return path.read_text(encoding="utf-8")
        except FileNotFoundError:
            logger.warning("Prompt file not found: %s", path)
            return ""

    async def generate(
        self,
        query: str,
        evidence: list[EvidenceItem],
        compound: Optional[CompoundProfile],
        trials: list[ClinicalTrial],
        targets: list[TargetProfile],
        search_mode: SearchMode = SearchMode.compound,
        analytics: Optional[TrialAnalytics] = None,
        strength: Optional[EvidenceStrength] = None,
        attribution: Optional[QueryAttributionSummary] = None,
    ) -> DossierResult:
        """Generate a Dossier, falling back to raw source data if the LLM is unusable."""

        def fallback(reason: str) -> DossierResult:
            logger.warning("AI synthesis skipped for '%s': %s", query, reason)
            return DossierResult(
                dossier=build_data_dossier(
                    query,
                    evidence,
                    compound,
                    trials,
                    targets,
                    reason=reason,
                    search_mode=search_mode,
                ),
                synthesized=False,
                detail=reason,
            )

        evidence_payload = self._build_evidence_payload(
            evidence, compound, trials, targets, analytics, strength, attribution
        )
        user_message = self._system_prompt.replace("{evidence_payload}", evidence_payload).replace(
            "{query}", query
        )

        try:
            raw_response = await self._call_openrouter(user_message)
        except DossierGenerationError as exc:
            return fallback(str(exc))

        # Attempt to parse JSON; one repair retry on failure
        dossier = self._parse_dossier(raw_response, query)
        if dossier is None:
            logger.warning("First parse attempt failed, requesting repair from model.")
            try:
                repaired = await self._repair_json(raw_response)
            except DossierGenerationError as exc:
                return fallback(str(exc))
            dossier = self._parse_dossier(repaired, query)
            if dossier is None:
                return fallback(
                    "The AI synthesis response could not be parsed into a valid dossier."
                )

        # Attach compound_profile from fetched data if LLM did not populate it
        if dossier.compound_profile is None and compound is not None:
            dossier = dossier.model_copy(update={"compound_profile": compound})

        # The reference list is assembled from the records that were actually
        # fetched. Letting the model retype ~80 citations costs a large share of
        # the output tokens and risks a misquoted identifier.
        dossier = dossier.model_copy(
            update={
                "references": build_references(evidence, compound, trials, targets)
            }
        )

        return DossierResult(dossier=dossier, synthesized=True, detail=None)

    def _build_evidence_payload(
        self,
        evidence: list[EvidenceItem],
        compound: Optional[CompoundProfile],
        trials: list[ClinicalTrial],
        targets: list[TargetProfile],
        analytics: Optional[TrialAnalytics] = None,
        strength: Optional[EvidenceStrength] = None,
        attribution: Optional[QueryAttributionSummary] = None,
    ) -> str:
        """Serialize top evidence items + structured data into a JSON string."""
        top_evidence = evidence[:_MAX_EVIDENCE_ITEMS]

        payload: dict = {
            "evidence_items": [
                {
                    "source": e.source,
                    "id": e.id,
                    "title": e.title,
                    "year": e.year,
                    "authors": e.authors[:5],  # cap authors for brevity
                    "abstract": (
                        condense(e.abstract, _MAX_ABSTRACT_CHARS) if e.abstract else None
                    ),
                    "url": e.url,
                    "evidence_type": e.evidence_type.value,
                    "relevance_score": round(e.relevance_score, 3),
                }
                for e in top_evidence
            ],
            "compound_profile": compound.model_dump() if compound else None,
            "clinical_trials": [
                {
                    "nct_id": t.nct_id,
                    "title": t.title,
                    "status": t.status,
                    "phase": t.phase,
                    "registry_status": t.overall_status,
                    "registry_phases": t.phases,
                    "conditions": t.conditions,
                    "interventions": t.interventions,
                    # The arm role is what the registry itself states about an
                    # intervention, so the narrative can say who receives it.
                    "interventions_with_registry_roles": [
                        {
                            "name": d.name,
                            "registry_type": d.type,
                            "registry_arm_role": d.role,
                            "arms": d.arm_group_labels,
                        }
                        for d in t.intervention_details
                    ],
                    "start_date": t.start_date,
                    "completion_date": t.completion_date,
                    "primary_completion_date": t.primary_completion_date,
                    "enrollment": t.enrollment_count,
                    "last_update_date": t.last_update_date,
                    # An outcome measure names the drug each assessment is about
                    # and the arm it belongs to, which an intervention list alone
                    # cannot show: a study can register two products in different
                    # cohorts without ever assessing one against the other.
                    "registry_outcome_measures": [
                        f"[{o.category}] {o.measure}" for o in t.outcomes[:12]
                    ],
                    "registry_outcome_time_points": t.outcome_time_frames,
                    "url": t.url,
                }
                for t in trials
            ],
            "protein_targets": [
                {
                    "accession": tgt.accession,
                    "name": tgt.name,
                    "gene": tgt.gene,
                    "organism": tgt.organism,
                    "function": tgt.function_summary,
                    "subcellular_location": tgt.subcellular_location,
                    "url": tgt.url,
                }
                for tgt in targets
            ],
            # Computed from the records above. These are the only figures the
            # narrative may state: the model is not asked to count, add or
            # average anything, and a number absent here has no support.
            "derived_counts_only": self._derived_counts(analytics, strength, attribution),
        }
        if attribution is not None and attribution.applicable:
            # Which retrieved trials the registry itself links to the query, so a
            # "studies of this product" sentence cannot be built from a keyword hit.
            payload["trial_attribution"] = {
                "rule": attribution.rule,
                "query_specific_trial_ids": sorted(
                    r.nct_id
                    for r in attribution.records
                    if r.category in ("direct", "comparator_or_combination")
                ),
                "categories": [
                    {"label": c.label, "count": c.count} for c in attribution.categories
                ],
                "reconciliation": attribution.reconciliation_note,
                "excluded_trial_ids_are_not_studies_of_the_product": True,
            }
        return json.dumps(payload, ensure_ascii=False, indent=2)

    @staticmethod
    def _derived_counts(
        analytics: Optional[TrialAnalytics],
        strength: Optional[EvidenceStrength],
        attribution: Optional[QueryAttributionSummary],
    ) -> dict:
        """Every number this dossier is allowed to state, and where it comes from."""
        counts: dict = {
            "note": (
                "These values are computed from the retrieved records. State no other "
                "count, total or percentage of records: a figure not listed here is not "
                "supported by this retrieval."
            ),
        }
        if analytics:
            counts["trials"] = {
                "distinct_trials": analytics.total_trials,
                "ongoing": analytics.ongoing_trials,
                "ongoing_definition": analytics.ongoing_definition,
                "registry_status_counts": {
                    group.label: group.count for group in analytics.status_groups
                },
                "status_group_definitions": {
                    group.label: group.definition for group in analytics.status_groups
                },
                "phase_counts": {b.label: b.count for b in analytics.trials_by_phase},
                "trials_with_unreported_phase": analytics.trials_with_unreported_phase,
            }
        if strength:
            counts["evidence"] = {
                "total_evidence_records": strength.total_records,
                "publications": strength.publication_records,
                "regulatory_label_passages": strength.regulatory_passages,
                "by_evidence_class": {c.label: c.count for c in strength.categories},
                "by_study_design": {d.label: d.count for d in strength.study_design_counts},
                "denominator": strength.denominator,
            }
        if attribution is not None and attribution.applicable:
            counts["trials_of_the_queried_product"] = {
                "direct": attribution.direct_trials,
                "as_comparator_or_combination": (
                    attribution.comparator_or_combination_trials
                ),
                "query_specific_total": attribution.query_specific_trials,
                "related_but_not_named": attribution.related_not_named_trials,
                "not_demonstrably_relevant": attribution.not_demonstrably_relevant_trials,
            }
        return counts

    async def _call_openrouter(self, user_message: str) -> str:
        """POST to OpenRouter and return the assistant message content."""
        if not self._api_key:
            raise DossierGenerationError(
                "AI synthesis is not configured on this server (OPENROUTER_API_KEY is not set)."
            )

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://moltel.local",
            "X-Title": "MolTel",
        }
        body = {
            "model": self._model,
            "messages": [
                {"role": "user", "content": user_message},
            ],
            "temperature": 0.2,
            "max_tokens": _MAX_OUTPUT_TOKENS,
            # Reasoning tokens are billed against max_tokens and add latency;
            # this task is structured extraction, so they are not wanted.
            "reasoning": {"enabled": False},
        }

        try:
            async with httpx.AsyncClient(timeout=_LLM_TIMEOUT_SECONDS) as client:
                response = await client.post(
                    _OPENROUTER_URL, headers=headers, json=body
                )
                response.raise_for_status()
                data = response.json()
        except httpx.TimeoutException as exc:
            raise DossierGenerationError(
                f"AI synthesis timed out before responding: {exc}"
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise DossierGenerationError(
                f"AI synthesis is unavailable (HTTP {exc.response.status_code})."
            ) from exc
        except Exception as exc:  # noqa: BLE001
            raise DossierGenerationError(
                f"AI synthesis request failed: {exc}"
            ) from exc

        try:
            choice = data["choices"][0]
            content: str = choice["message"]["content"]
        except (KeyError, IndexError) as exc:
            raise DossierGenerationError(
                f"AI synthesis returned an unexpected response structure: {exc}"
            ) from exc

        # A truncated reply cannot be repaired by re-asking, so fail fast to the
        # data dossier rather than spending a second long call on it.
        if choice.get("finish_reason") == "length":
            raise DossierGenerationError(
                "AI synthesis output was cut off before completing the dossier."
            )

        return content

    async def _repair_json(self, broken_json: str) -> str:
        """Ask the model to repair its own broken JSON output."""
        repair_prompt = (
            "The following text was supposed to be a JSON object but failed to parse. "
            "Fix it so it is valid JSON matching the dossier schema and return ONLY the "
            "corrected JSON object with no additional text or markdown fences.\n\n"
            f"{broken_json}"
        )
        return await self._call_openrouter(repair_prompt)

    @staticmethod
    def _parse_dossier(raw: str, query: str) -> Optional[Dossier]:
        """Attempt to parse raw LLM output into a Dossier model."""
        if not raw:
            return None
        # Strip markdown code fences if present
        text = raw.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            # Remove first and last fence lines
            start = 1 if lines[0].startswith("```") else 0
            end = len(lines) - 1 if lines[-1].strip() == "```" else len(lines)
            text = "\n".join(lines[start:end])

        try:
            data = json.loads(text)
            if "query" not in data:
                data["query"] = query
            for field in _DOSSIER_TEXT_FIELDS:
                if field in data:
                    data[field] = _as_text(data[field])
            # The real compound profile is attached from fetched data afterwards,
            # so a malformed one from the model is dropped rather than fatal.
            if not isinstance(data.get("compound_profile"), dict):
                data["compound_profile"] = None
            refs = data.get("references")
            if isinstance(refs, list):
                data["references"] = [t for t in (_as_text(r) for r in refs) if t]
            elif refs is None:
                data["references"] = []
            else:
                data["references"] = [t for t in [_as_text(refs)] if t]

            # These two panels are validated separately and re-attached, so a
            # malformed entry degrades one panel instead of failing the parse.
            contradictions = _parse_contradictions(data.get("contradictory_findings"))
            gaps = _parse_research_gaps(
                data.get("research_gap_analysis") or data.get("research_gaps")
            )
            data.pop("contradictory_findings", None)
            data.pop("research_gap_analysis", None)
            data.pop("research_gaps", None)
            dossier = Dossier.model_validate(data)
            return dossier.model_copy(
                update={
                    "contradictory_findings": contradictions,
                    "research_gap_analysis": gaps,
                }
            )
        except (json.JSONDecodeError, Exception) as exc:  # noqa: BLE001
            logger.warning("Dossier JSON parse failed: %s", exc)
            return None
