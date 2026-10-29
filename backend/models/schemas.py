"""MolTel — Pydantic v2 request/response models."""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class EvidenceType(str, Enum):
    clinical = "clinical"
    randomized_controlled_trial = "randomized_controlled_trial"
    systematic_review = "systematic_review"
    observational = "observational"
    case_report = "case_report"
    animal = "animal"
    cellular = "cellular"
    biochemical = "biochemical"
    computational = "computational"
    literature_review = "literature_review"
    editorial = "editorial"
    correction_or_retraction = "correction_or_retraction"
    regulatory = "regulatory"
    AI_hypothesis = "AI_hypothesis"
    # The source record carried no publication type this map understands.
    other = "other"


class LiteratureView(str, Enum):
    """How a literature list is ordered. Each view answers a different question,
    so 'latest' and 'most relevant' are kept separate rather than blended."""

    most_relevant = "most_relevant"
    latest = "latest"
    strongest_evidence = "strongest_evidence"
    reviews_guidelines = "reviews_guidelines"


class RankReason(BaseModel):
    """One stated reason a record sits where it does in a literature view.

    A view is a sort rule, never a quality judgement: no numeric "quality score"
    is produced, and each reason names the retrieved field it came from.
    """

    label: str
    # The retrieved field the rule read, e.g. 'title', 'publication_types'.
    source_field: str


class EvidenceItem(BaseModel):
    source: str
    source_type: str  # e.g. 'literature', 'regulatory', 'clinical_trial'
    id: Optional[str] = None
    title: Optional[str] = None
    year: Optional[int] = None
    authors: list[str] = Field(default_factory=list)
    abstract: Optional[str] = None
    url: Optional[str] = None
    evidence_type: EvidenceType = EvidenceType.other
    relevance_score: float = 0.0
    metadata: dict[str, Any] = Field(default_factory=dict)

    # --- Literature record detail (spec §7) ---------------------------------
    # Identifiers the dedupe keys on. Kept as explicit fields because a record
    # can carry all three and they are what proves two records are the same
    # paper; a title looking similar is not.
    pmid: Optional[str] = None
    pmcid: Optional[str] = None
    doi: Optional[str] = None
    # Date the article was published, as the source states it. `published_precision`
    # says how much the source resolved: a source giving only a year is recorded
    # as year, not padded into a full date.
    published_on: Optional[str] = None
    published_precision: Optional[str] = None
    # Date the database indexed the record. Reported apart from publication date
    # because the two are different claims and a recent index date is not a new
    # paper.
    indexed_on: Optional[str] = None
    indexed_field: Optional[str] = None
    # How the source labels its own publication types, kept verbatim so an
    # editorial or correction can be shown as the source names it.
    publication_types: list[str] = Field(default_factory=list)
    open_access: Optional[bool] = None
    journal: Optional[str] = None
    # Every link the retrieved records carry for this paper. Deduping merges
    # records but never discards a source link.
    links: list[str] = Field(default_factory=list)
    # How many source records this item was built from, and which sources.
    merged_records: int = 1
    merged_sources: list[str] = Field(default_factory=list)
    # Why this record is where it is in the view it was returned for.
    rank_reasons: list[RankReason] = Field(default_factory=list)
    # Which view produced the current ordering, so the UI can label it.
    view: Optional[LiteratureView] = None


class CompoundProfile(BaseModel):
    cid: Optional[str] = None
    name: Optional[str] = None
    synonyms: list[str] = Field(default_factory=list)
    molecular_formula: Optional[str] = None
    molecular_weight: Optional[str] = None
    canonical_smiles: Optional[str] = None
    isomeric_smiles: Optional[str] = None
    iupac_name: Optional[str] = None
    inchi_key: Optional[str] = None


class TrialOutcome(BaseModel):
    """An outcome the registry lists for a study.

    A measure names the drug or endpoint that assessment is about, which an
    intervention list alone cannot show: a study can register two products and
    still measure only one of them against a third.
    """

    measure: str
    # "primary" or "secondary", as the registry files it.
    category: str = "primary"


class TrialArmGroup(BaseModel):
    """One study arm exactly as the registry describes it.

    The arm type is the only place the registry states an intervention's *role*,
    so candidate and attribution counts use it instead of guessing from wording.
    """

    label: str
    # Registry code: EXPERIMENTAL | ACTIVE_COMPARATOR | PLACEBO_COMPARATOR |
    # SHAM_COMPARATOR | OTHER.
    type: Optional[str] = None
    intervention_names: list[str] = Field(default_factory=list)


class TrialIntervention(BaseModel):
    """One intervention exactly as the registry lists it.

    `type` is the registry's own codes (DRUG, BIOLOGICAL, DEVICE, BEHAVIORAL,
    ...). Candidate extraction depends on it, so an absent type is left as None
    rather than assumed to mean a drug.
    """

    name: str
    type: Optional[str] = None
    description: Optional[str] = None
    # Arm labels the registry links this intervention to, and the role the
    # registry gives it through those arms. Both stay None/empty when the
    # record does not state them — a role is never inferred from the name.
    arm_group_labels: list[str] = Field(default_factory=list)
    role: Optional[str] = None


class TrialCollaborator(BaseModel):
    name: str
    # Registry class: INDUSTRY | ACADEMIC | GOVERNMENT | INTERNATIONAL | OTHER.
    # Named registry_class so the JSON key matches the Python field exactly.
    registry_class: Optional[str] = None


class ClinicalTrial(BaseModel):
    """A normalized registry record.

    `status`/`phase`/`url` are display labels kept for the dossier tables; the
    `*_category` fields carry the transparent dashboard classification from
    services/trial_taxonomy.py, and the raw registry values are preserved
    alongside them so nothing is inferred that the source did not state.
    """

    nct_id: str
    title: Optional[str] = None
    status: Optional[str] = None
    phase: Optional[str] = None
    conditions: list[str] = Field(default_factory=list)
    interventions: list[str] = Field(default_factory=list)
    sponsor: Optional[str] = None
    study_type: Optional[str] = None
    url: Optional[str] = None

    # Per-intervention detail, needed to tell a studied product from a study.
    intervention_details: list[TrialIntervention] = Field(default_factory=list)
    arm_groups: list[TrialArmGroup] = Field(default_factory=list)
    collaborators: list[TrialCollaborator] = Field(default_factory=list)
    outcomes: list[TrialOutcome] = Field(default_factory=list)
    # Every distinct time frame the registry states for these outcomes.
    outcome_time_frames: list[str] = Field(default_factory=list)

    # Raw registry values, preserved for provenance.
    overall_status: Optional[str] = None
    phases: list[str] = Field(default_factory=list)
    # Derived, auditable classifications.
    status_category: Optional[str] = None
    status_category_label: Optional[str] = None
    phase_category: Optional[str] = None
    ongoing: bool = False

    # Optional record detail — absent whenever the registry did not supply it.
    brief_summary: Optional[str] = None
    start_date: Optional[str] = None
    primary_completion_date: Optional[str] = None
    completion_date: Optional[str] = None
    enrollment_count: Optional[int] = None
    enrollment_type: Optional[str] = None
    last_update_date: Optional[str] = None
    source_url: Optional[str] = None
    retrieved_at: Optional[str] = None


class TargetProfile(BaseModel):
    accession: str
    name: Optional[str] = None
    gene: Optional[str] = None
    organism: Optional[str] = None
    function_summary: Optional[str] = None
    subcellular_location: Optional[str] = None
    url: Optional[str] = None


class DossierSection(BaseModel):
    title: str
    content: str
    evidence_items: list[EvidenceItem] = Field(default_factory=list)
    citations: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Clinical trial analytics
# ---------------------------------------------------------------------------

class TrialRetrievalMetadata(BaseModel):
    """Search transparency: what was asked, when, and how much came back."""

    query: str
    retrieved_at: Optional[str] = None
    records_returned: int = 0
    total_available: Optional[int] = None
    has_more: bool = False
    partial: bool = False
    # False means the registry could not be consulted at all. That is a
    # different statement from "no trials were found".
    source_reached: bool = True
    source: str = "ClinicalTrials.gov"
    note: Optional[str] = None


class ChartBucket(BaseModel):
    label: str
    count: int


class StatusBucket(ChartBucket):
    category: str


class StatusGroup(BaseModel):
    """One derived dashboard category, the registry statuses inside it, and its count.

    The membership travels with the number so a heading cannot drift away from the
    arithmetic that produced it.
    """

    category: str
    label: str
    definition: str
    registry_statuses: list[str] = Field(default_factory=list)
    count: int = 0


class TrialStartPeriod(BaseModel):
    period: str
    count: int


class TrialAnalytics(BaseModel):
    """Counts derived deterministically from deduplicated registry records."""

    total_trials: int = 0
    ongoing_trials: int = 0
    # Strictly the registry status RECRUITING. The category that also folds in
    # "Enrolling by invitation" is reported separately as currently_recruiting.
    recruiting_trials: int = 0
    enrolling_by_invitation_trials: int = 0
    currently_recruiting_trials: int = 0
    active_not_recruiting_trials: int = 0
    not_yet_recruiting_trials: int = 0
    completed_trials: int = 0
    discontinued_trials: int = 0
    paused_trials: int = 0
    other_status_trials: int = 0
    trials_with_unreported_phase: int = 0
    trials_by_phase: list[ChartBucket] = Field(default_factory=list)
    ongoing_trials_by_phase: list[ChartBucket] = Field(default_factory=list)
    trials_by_status: list[StatusBucket] = Field(default_factory=list)
    # Derived groups with their membership stated, plus the reconciliation the
    # pre-publication gate checks.
    status_groups: list[StatusGroup] = Field(default_factory=list)
    ongoing_definition: str = ""
    exclusive_status_total: int = 0
    statuses_reconcile: bool = True
    trial_starts_by_period: list[TrialStartPeriod] = Field(default_factory=list)
    timeline_granularity: Optional[str] = None
    timeline_omitted_reason: Optional[str] = None
    excluded_from_timeline_count: int = 0
    metadata: TrialRetrievalMetadata


class CandidatePhaseBucket(BaseModel):
    """One phase of one candidate, with the trials behind it."""

    phase: str
    phase_category: str
    trials: int
    nct_ids: list[str] = Field(default_factory=list)


class CandidateRecord(BaseModel):
    """A product named as a registry intervention, plus the trials that name it.

    Sponsorship, label manufacture and development are three different claims.
    The first two come straight from a retrieved record; the third is only ever
    stated when a retrieved source states it, otherwise the record reads
    "Developer not established". openFDA drug labels name a manufacturer and an
    application number but not an application holder, so no marketing
    authorization holder is asserted here.
    """

    name: str
    matched_names: list[str] = Field(default_factory=list)
    intervention_types: list[str] = Field(default_factory=list)
    # The arm roles the registry states wherever this product is registered. A
    # placebo arm labelled with the product's own name does not make the product
    # a comparator, so the role is read from the arm, never from the wording.
    registry_roles: list[str] = Field(default_factory=list)
    trials: int = 0
    nct_ids: list[str] = Field(default_factory=list)
    phases: list[CandidatePhaseBucket] = Field(default_factory=list)
    highest_phase: Optional[str] = None
    statuses: list[StatusBucket] = Field(default_factory=list)
    ongoing_trials: int = 0
    conditions: list[str] = Field(default_factory=list)
    sponsors: list[str] = Field(default_factory=list)
    collaborators: list[str] = Field(default_factory=list)
    # Taken from an openFDA label whose product name matches this candidate.
    fda_application_number: Optional[str] = None
    label_manufacturer: Optional[str] = None
    label_source_url: Optional[str] = None
    developer: Optional[str] = None
    developer_note: str = "Developer not established"
    # Set only when a label matched: a label manufacturer is not necessarily the
    # application holder, and no retrieved source states development from it.
    label_note: str = ""
    start_date: Optional[str] = None
    completion_date: Optional[str] = None
    last_update_date: Optional[str] = None
    retrieved_at: Optional[str] = None
    source_links: list[str] = Field(default_factory=list)


class CompanyPhaseCount(BaseModel):
    company: str
    phase: str
    candidates: int
    # How the company is attached to the candidate: the registry's lead sponsor
    # or the manufacturer printed on a retrieved openFDA label. Never described
    # as development.
    attribution: str


class CandidateAnalytics(BaseModel):
    """Deterministic candidate counts from the same deduplicated trial list."""

    distinct_candidates: int = 0
    candidate_trials_considered: int = 0
    trials_without_named_intervention: int = 0
    candidates_by_phase: list[ChartBucket] = Field(default_factory=list)
    ongoing_candidates_by_phase: list[ChartBucket] = Field(default_factory=list)
    candidates_by_company: list[ChartBucket] = Field(default_factory=list)
    company_by_phase: list[CompanyPhaseCount] = Field(default_factory=list)
    candidates_with_established_developer: int = 0
    candidates_with_openfda_label: int = 0
    # Placebo/sham names the registry types as drug interventions. They remain in
    # the counts; the number is reported so the list is not read as a pipeline.
    comparator_candidates: int = 0
    non_drug_intervention_types: list[ChartBucket] = Field(default_factory=list)
    records: list[CandidateRecord] = Field(default_factory=list)
    counting_rule: str = (
        "A candidate is a distinct intervention name the registry types as a drug, "
        "biological, dietary supplement or combination product. Names are matched "
        "case-insensitively after whitespace collapse only — salts, esters and "
        "formulations are never merged. A candidate is counted once per phase "
        "category it appears in, so the by-phase totals sum above the number of "
        "distinct candidates whenever a product was studied in more than one phase. "
        "Company counts use only organizations named on a retrieved record — the "
        "registry's lead sponsor, or the manufacturer printed on an openFDA label "
        "whose product name matches — and never a developer inferred from either. "
        "A named comparator such as placebo is listed because the registry types it "
        "as a drug intervention, not because it is a candidate in development; the "
        "comparator count gives how many of these there are."
    )
    metadata: TrialRetrievalMetadata


class AttributionCategory(BaseModel):
    """One attribution category, its definition and how many trials landed in it."""

    key: str
    label: str
    count: int = 0
    # What puts a trial in this row, carried with the number so a heading and its
    # evidence cannot be read apart.
    basis: str = ""


class QueryAttribution(BaseModel):
    """One trial and the structured registry evidence for its relationship to the query."""

    nct_id: str
    title: Optional[str] = None
    category: str
    category_label: str
    basis: str = ""
    matched_interventions: list[str] = Field(default_factory=list)
    registry_roles: list[str] = Field(default_factory=list)
    source_url: Optional[str] = None


class QueryAttributionSummary(BaseModel):
    """Trials sorted by what the registry actually states about the queried product.

    Kept separate from `CandidateAnalytics` on purpose: how many studies exist of
    a product and how many products were studied are two different questions, and
    a count that mixes placebos, procedures and somebody else's investigational
    drug cannot be read as that product's development pipeline.
    """

    query: str
    applicable: bool = True
    reason: str = ""
    distinct_trials: int = 0
    direct_trials: int = 0
    comparator_or_combination_trials: int = 0
    query_specific_trials: int = 0
    related_not_named_trials: int = 0
    not_demonstrably_relevant_trials: int = 0
    categories: list[AttributionCategory] = Field(default_factory=list)
    records: list[QueryAttribution] = Field(default_factory=list)
    excluded_nct_ids: list[str] = Field(default_factory=list)
    distinct_intervention_names: int = 0
    placebo_or_sham_arms: int = 0
    distinct_investigational_candidates: int = 0
    placebo_or_sham_names: list[str] = Field(default_factory=list)
    rule: str = ""
    reconciliation_note: str = ""


class TrialsResponse(BaseModel):
    query: str
    trials: list[ClinicalTrial] = Field(default_factory=list)
    metadata: TrialRetrievalMetadata
    analytics: Optional[TrialAnalytics] = None
    candidate_analytics: Optional[CandidateAnalytics] = None


# ---------------------------------------------------------------------------
# Disease intelligence (spec §6)
# ---------------------------------------------------------------------------

class SearchMode(str, Enum):
    """What MolTel was asked to search for. Shown in the UI so a reader can tell
    which sources the results came from."""

    compound = "compound"
    disease = "disease"
    target = "target"


class DiseaseTerm(BaseModel):
    """One disease concept exactly as a standardized ontology names it."""

    label: str
    concept_id: Optional[str] = None
    ontology: Optional[str] = None
    url: Optional[str] = None
    iri: Optional[str] = None
    definition: Optional[str] = None
    synonyms: list[str] = Field(default_factory=list)
    # The broader concept the ontology itself places this term under, when the
    # hierarchy was read from the source rather than inferred from wording.
    parent: Optional[str] = None
    parent_concept_id: Optional[str] = None
    # Synonym strings the concept record carries but this display leaves out,
    # because they name a genetic association rather than the disease. The count
    # is reported so the omission is visible; the source record is untouched.
    excluded_synonyms: int = 0


class DiseaseConcept(BaseModel):
    """What the ontology lookup returned for the submitted query."""

    query: str
    source: str = "OBO Foundry disease ontologies via EBI OLS4"
    source_reached: bool = False
    # Whether the ontology's own child concepts of the matched term were read.
    # When they could not be, the subtype list falls back to the concepts the
    # search returned and to the wording the retrieved records carry.
    hierarchy_reached: bool = False
    retrieved_at: Optional[str] = None
    canonical: Optional[DiseaseTerm] = None
    # Narrower concepts: the matched term's own children in the ontology, plus
    # narrower wording the search returned for the same query.
    related: list[DiseaseTerm] = Field(default_factory=list)
    excluded_related: int = 0
    note: Optional[str] = None


class DiseaseSubtype(BaseModel):
    """A subtype with the retrieved records that name it.

    A record is attached only when it carries the subtype wording itself. No
    disease relationship is inferred, so a subtype with no records describes this
    retrieved set — not whether research on it exists.
    """

    label: str
    # "standardized concept", "registry condition wording", or "both".
    origin: str
    concept: Optional[DiseaseTerm] = None
    # The term this subtype refines: another subtype in this list, or the
    # canonical term. refines_source says whether that relation was read from the
    # ontology's hierarchy or follows from the wording alone.
    refines: Optional[str] = None
    refines_source: Optional[str] = None
    level: int = 0
    condition_labels: list[str] = Field(default_factory=list)
    trial_nct_ids: list[str] = Field(default_factory=list)
    candidate_names: list[str] = Field(default_factory=list)
    company_names: list[str] = Field(default_factory=list)
    paper_keys: list[str] = Field(default_factory=list)
    target_accessions: list[str] = Field(default_factory=list)
    availability_note: str = ""


class DiseaseAnalytics(BaseModel):
    """Deterministic disease view built from the retrieved records."""

    query: str
    # Canonical term plus where it came from: an ontology concept, or the most
    # frequent condition string in the retrieved records when no concept matched.
    canonical_term: str
    canonical_term_provenance: str
    concept: Optional[DiseaseTerm] = None
    synonyms: list[str] = Field(default_factory=list)
    subtypes: list[DiseaseSubtype] = Field(default_factory=list)
    # Condition strings the retrieved trials name that no subtype above covers.
    # They are counted in the query totals and named here rather than dropped.
    unmatched_condition_labels: list[ChartBucket] = Field(default_factory=list)
    trials_considered: int = 0
    trials_with_condition_label: int = 0
    trials_without_condition_label: int = 0
    papers_considered: int = 0
    targets_considered: int = 0
    candidates_considered: int = 0
    subtypes_with_records: int = 0
    subtypes_without_records: int = 0
    subtypes_omitted: int = 0
    ontology_reached: bool = False
    counting_rule: str = (
        "A subtype is listed when the disease ontology names it or a retrieved "
        "registry record uses its wording. A trial is attached to a subtype only "
        "when its own condition list or brief title carries that name in full: "
        "words are compared case-insensitively with punctuation, plurals and "
        "connecting words folded away, word order is not required to match, a "
        "word introduced by 'non-' or 'no-' counts as denied rather than used, "
        "and a bracketed abbreviation may stand for the words beside it because "
        "it names the same thing. A bracketed word that only says what kind of "
        "record a name is — '(disease)' in 'meningioma (disease) of lung' — names "
        "nothing, so it is not used to match. Candidates and companies come from trials "
        "already attached to the subtype, papers from a title or abstract "
        "carrying the same name, and targets from a target record that names it — "
        "never from an inferred disease relationship. A registry condition string "
        "that repeats a name the ontology recorded for a listed concept is filed "
        "under that concept; a string that only repeats part of the queried "
        "disease's name is broader than the query, so it is reported as other "
        "condition wording rather than as a subtype. Other condition strings are "
        "those the retrieved trials name that no subtype here covers, and they "
        "stay in the query totals. A subtype with no records means none were "
        "retrieved here, not that none exist."
    )
    hierarchy_note: str = (
        "Where the disease ontology states that one concept is a child of "
        "another, that relation is shown as the source publishes it, to two "
        "levels below the matched term. Elsewhere nesting follows wording: a "
        "subtype is filed under the closest listed name whose words it uses in "
        "full, and a name formed by denying part of another name is not filed "
        "under the wording it denies. MolTel does not assert a validated disease "
        "classification, and one subtype being listed under another is not a "
        "clinical claim."
    )
    limitations: list[str] = Field(default_factory=list)
    metadata: Optional[TrialRetrievalMetadata] = None


# ---------------------------------------------------------------------------
# Research intelligence
# ---------------------------------------------------------------------------

class EvidenceDeduplication(BaseModel):
    """How retrieved records were merged into publications, shown with the list.

    Merging is only ever done on identifiers a source states for the paper, so
    the counts here say how many records were the same publication and how many
    carried no identifier to merge on.
    """

    records_received: int = 0
    publications: int = 0
    # records_received - publications: how many records folded into another.
    records_merged: int = 0
    # Publications built from more than one retrieved record.
    merged_publications: int = 0
    # Of those, the ones whose records came from different databases.
    cross_database_merges: int = 0
    # Records with no PMID, PMCID or DOI to merge on, so listed on their own.
    records_without_identifier: int = 0
    matched_on: list[str] = Field(default_factory=lambda: ["PMID", "PMCID", "DOI"])
    never_matched_on: list[str] = Field(
        default_factory=lambda: ["title similarity", "author similarity"]
    )
    rule: str = (
        "Two records are the same publication only when a PMID, PMCID or DOI "
        "matches between them. A merged publication keeps every source link, "
        "identifier and publication type from the records it was built from; "
        "no record is discarded. Titles are never compared to decide a merge."
    )


class LiteratureFilters(BaseModel):
    """Record-level filters offered over a retrieved literature set.

    Every filter reads a field the source states. A record the source gives no
    value for is dropped by that filter and counted, because "not stated" is not
    the same as "not open access" or "not a review".
    """

    published_from: Optional[str] = None
    published_to: Optional[str] = None
    evidence_types: list[EvidenceType] = Field(default_factory=list)
    # "clinical" = a study of people as the source reports it; "preclinical" =
    # animal, cellular/biochemical or computational work. Neither is a claim that
    # the finding applies to patients.
    study_scope: Optional[str] = None
    open_access: Optional[bool] = None
    sources: list[str] = Field(default_factory=list)
    # Matched against the publication-type strings the source itself reported.
    publication_types: list[str] = Field(default_factory=list)
    subtype_label: Optional[str] = None
    # Names of targets retrieved for this query; used only by relevance_to_target.
    target_terms: list[str] = Field(default_factory=list)
    relevance_to_target: Optional[bool] = None


class LiteratureExclusion(BaseModel):
    """One filter and how many records it removed."""

    filter: str
    label: str
    removed: int
    # What the filter did to records the source left blank, stated so a count is
    # not read as "zero records of that kind exist".
    note: Optional[str] = None


class LiteratureFacet(BaseModel):
    """A filter option and how many retrieved records fall under it."""

    field: str
    value: str
    count: int
    # Whether the source states this for the record, or the platform classified it.
    stated_by_source: bool = True


class LiteratureViewRequest(BaseModel):
    """Re-rank records the client already holds, so no source is queried twice."""

    items: list[EvidenceItem] = Field(default_factory=list)
    query: str
    view: LiteratureView = LiteratureView.most_relevant
    filters: Optional[LiteratureFilters] = None


class LiteratureViewResult(BaseModel):
    """A literature list ordered by one view's rule, with the rule shown."""

    view: LiteratureView
    label: str
    rule: str
    ordered_by: list[str] = Field(default_factory=list)
    items: list[EvidenceItem] = Field(default_factory=list)
    records_received: int = 0
    records_shown: int = 0
    exclusions: list[LiteratureExclusion] = Field(default_factory=list)
    facets: list[LiteratureFacet] = Field(default_factory=list)
    deduplication: Optional[EvidenceDeduplication] = None
    dates_note: str = (
        "Dates are the publication dates the sources state, at the precision they "
        "state them. A database's indexing date is reported separately and is "
        "never used as a publication date."
    )
    limitations: list[str] = Field(default_factory=list)


class EvidenceCategory(BaseModel):
    key: str
    label: str
    count: int = 0
    # What one unit of this count is. Stated because the classes mix publications
    # with label passages, and a total without a unit reads as a publication count.
    unit: str = "evidence record"
    # The rule this class used, shown in the UI so the grouping is auditable.
    criteria: str = ""
    records: list[str] = Field(default_factory=list)


class StudyDesignCount(BaseModel):
    """A study-design tally with the records that produced it.

    These are the only record counts the narrative is allowed to quote, so each
    one carries its own definition and denominator and can be recounted by hand.
    """

    label: str
    definition: str
    count: int = 0
    records: list[str] = Field(default_factory=list)
    denominator: str = ""


class EvidenceStrength(BaseModel):
    """Deterministic tally of retrieved records by evidence tier.

    Deliberately count-based: no numeric "strength score" is computed, because
    publication volume alone does not establish evidence quality.
    """

    categories: list[EvidenceCategory] = Field(default_factory=list)
    predominant_tier: Optional[str] = None
    interpretation: Optional[str] = None
    limitations: list[str] = Field(default_factory=list)
    unclassified_count: int = 0
    automated: bool = True
    # The denominator every class count is taken against, stated rather than
    # assumed, plus the split that explains why it differs from the publication
    # count a reader sees in the literature table.
    total_records: int = 0
    publication_records: int = 0
    regulatory_passages: int = 0
    mutually_exclusive: bool = True
    denominator: str = ""
    reconciles: bool = True
    study_design_counts: list[StudyDesignCount] = Field(default_factory=list)


class Contradiction(BaseModel):
    claim: Optional[str] = None
    study_a: Optional[str] = None
    study_b: Optional[str] = None
    context_difference: Optional[str] = None
    possible_explanation: Optional[str] = None
    classification: Optional[str] = None
    confidence: Optional[str] = None
    missing_information: Optional[str] = None
    citations: list[str] = Field(default_factory=list)


class ContradictoryFindings(BaseModel):
    contradictions: list[Contradiction] = Field(default_factory=list)
    assessment: Optional[str] = None
    insufficient_evidence: bool = False


class ResearchGap(BaseModel):
    question: Optional[str] = None
    current_evidence: Optional[str] = None
    uncertainty: Optional[str] = None
    why_it_matters: Optional[str] = None
    next_step: Optional[str] = None
    confidence: Optional[str] = None
    label: Optional[str] = None
    references: list[str] = Field(default_factory=list)


class Dossier(BaseModel):
    query: str
    executive_summary: Optional[str] = None
    compound_profile: Optional[CompoundProfile] = None
    mechanism: Optional[str] = None
    therapeutic_evidence: Optional[str] = None
    literature_summary: Optional[str] = None
    clinical_development: Optional[str] = None
    safety: Optional[str] = None
    evidence_gaps: Optional[str] = None
    research_opportunities: Optional[str] = None
    contradictory_findings: Optional[ContradictoryFindings] = None
    research_gap_analysis: list[ResearchGap] = Field(default_factory=list)
    references: list[str] = Field(default_factory=list)
    sources_status: list["SourceStatus"] = Field(default_factory=list)


class DossierRequest(BaseModel):
    query: str
    # Defaults to a compound search, which is how every existing client calls it.
    search_mode: SearchMode = SearchMode.compound


class SourceStatus(BaseModel):
    source_name: str
    # 'success', 'error', 'no_results', or 'skipped' — skipped means MolTel did
    # not query this source for this search mode, which is not a source failure.
    status: str
    count: int = 0
    error_message: Optional[str] = None
    note: Optional[str] = None


class ValidationFinding(BaseModel):
    """One pre-publication check result, stated so a reader can act on it.

    Nothing here edits the report. A claim that cannot be supported is named and
    labelled for review, because silently repairing source-derived prose would
    hide the disagreement the reader needs to see.
    """

    rule: str
    # 'error' blocks publication; 'warning' is published with the finding shown.
    severity: str
    field: str
    quote: str = ""
    expected: Optional[str] = None
    observed: Optional[str] = None
    source_ref: Optional[str] = None
    suggested_correction: Optional[str] = None
    status: str = "fail"
    blocks_publication: bool = False


class ValidationReport(BaseModel):
    """Machine-readable QA output published alongside every dossier."""

    errors: int = 0
    warnings: int = 0
    blocked: bool = False
    findings: list[ValidationFinding] = Field(default_factory=list)
    rules_run: list[str] = Field(default_factory=list)
    checked_fields: list[str] = Field(default_factory=list)
    generated_at: Optional[str] = None
    note: str = (
        "Errors contradict a retrieved record; warnings mark weaker evidence or "
        "incomplete retrieval. The gate never changes a claim — it names the "
        "disagreement and the source that would settle it."
    )
    override: bool = False
    override_reason: Optional[str] = None


class DossierResponse(BaseModel):
    query: str
    status: str  # 'success', 'partial', 'error'
    search_mode: SearchMode = SearchMode.compound
    sources: list[SourceStatus] = Field(default_factory=list)
    dossier: Optional[Dossier] = None
    # Whether the narrative sections came from the model or from raw source data
    ai_synthesized: bool = False
    synthesis_detail: Optional[str] = None
    # Raw structured data for frontend tables (not summarised by LLM)
    evidence_items: list[EvidenceItem] = Field(default_factory=list)
    clinical_trials: list[ClinicalTrial] = Field(default_factory=list)
    targets: list[TargetProfile] = Field(default_factory=list)
    # Computed in memory from the records above — never from the model
    evidence_strength: Optional[EvidenceStrength] = None
    trial_analytics: Optional[TrialAnalytics] = None
    candidate_analytics: Optional[CandidateAnalytics] = None
    # Which retrieved trials actually name the queried product, per §2 of the
    # research-safety rules: a registry hit is not an attribution.
    query_attribution: Optional[QueryAttributionSummary] = None
    # Pre-publication gate. Rendered in the report so a blocked claim is visible
    # to the reader rather than fixed behind their back.
    validation: Optional[ValidationReport] = None
    publication_blocked: bool = False
    # Only computed for a disease search; a compound query has no subtype to resolve.
    disease_analytics: Optional[DiseaseAnalytics] = None
    # The literature ordering this response was built with: its rule, the counts
    # each filter would remove, and how records were merged into publications.
    # `items` is empty here — the ordered records are the literature subset of
    # evidence_items, and another view is asked for at /api/literature/views.
    literature: Optional[LiteratureViewResult] = None
    retrieved_at: Optional[str] = None


# Rebuild forward references
Dossier.model_rebuild()
