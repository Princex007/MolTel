/**
 * API client for the MolTel backend.
 * All types mirror backend/models/schemas.py exactly.
 */

const API_BASE =
  typeof process !== "undefined" && process.env.NEXT_PUBLIC_API_URL
    ? process.env.NEXT_PUBLIC_API_URL
    : ""; // empty string → Next.js rewrite proxy handles /api/*

// ─── Types ────────────────────────────────────────────────────────────────────

export type EvidenceType =
  | "clinical"
  | "randomized_controlled_trial"
  | "systematic_review"
  | "observational"
  | "case_report"
  | "animal"
  | "cellular"
  | "biochemical"
  | "computational"
  | "literature_review"
  | "editorial"
  | "correction_or_retraction"
  | "regulatory"
  | "AI_hypothesis"
  | "other";

export type LiteratureView =
  | "most_relevant"
  | "latest"
  | "strongest_evidence"
  | "reviews_guidelines";

/** One stated reason a record sits where it does in the view it was returned for. */
export interface RankReason {
  label: string;
  // The retrieved field the rule read, e.g. "title", "publication_types".
  source_field: string;
}

export interface EvidenceItem {
  source: string;
  source_type: string;
  id: string | null;
  title: string | null;
  year: number | null;
  authors: string[];
  abstract: string | null;
  url: string | null;
  evidence_type: EvidenceType;
  relevance_score: number;
  metadata: Record<string, unknown>;
  // Literature record detail. Every field is what the source states, or null
  // when the source states nothing — an absent date is not an invented one.
  pmid: string | null;
  pmcid: string | null;
  doi: string | null;
  published_on: string | null;
  published_precision: "day" | "month" | "year" | null;
  indexed_on: string | null;
  indexed_field: string | null;
  publication_types: string[];
  open_access: boolean | null;
  journal: string | null;
  links: string[];
  merged_records: number;
  merged_sources: string[];
  rank_reasons: RankReason[];
  view: LiteratureView | null;
}

export interface EvidenceDeduplication {
  records_received: number;
  publications: number;
  records_merged: number;
  merged_publications: number;
  cross_database_merges: number;
  records_without_identifier: number;
  matched_on: string[];
  never_matched_on: string[];
  rule: string;
}

export interface LiteratureFilters {
  published_from?: string | null;
  published_to?: string | null;
  evidence_types?: EvidenceType[];
  study_scope?: "clinical" | "preclinical" | null;
  open_access?: boolean | null;
  sources?: string[];
  publication_types?: string[];
  subtype_label?: string | null;
  target_terms?: string[];
  relevance_to_target?: boolean | null;
}

export interface LiteratureExclusion {
  filter: string;
  label: string;
  removed: number;
  note: string | null;
}

export interface LiteratureFacet {
  field: string;
  value: string;
  count: number;
  stated_by_source: boolean;
}

export interface LiteratureViewResult {
  view: LiteratureView;
  label: string;
  rule: string;
  ordered_by: string[];
  items: EvidenceItem[];
  records_received: number;
  records_shown: number;
  exclusions: LiteratureExclusion[];
  facets: LiteratureFacet[];
  deduplication: EvidenceDeduplication | null;
  dates_note: string;
  limitations: string[];
}

export interface CompoundProfile {
  cid: string | null;
  name: string | null;
  synonyms: string[];
  molecular_formula: string | null;
  molecular_weight: string | null;
  canonical_smiles: string | null;
  isomeric_smiles: string | null;
  iupac_name: string | null;
  inchi_key: string | null;
}

export interface TrialIntervention {
  name: string;
  /** The registry's own code: DRUG, BIOLOGICAL, DEVICE, BEHAVIORAL, … */
  type: string | null;
}

export interface TrialCollaborator {
  name: string;
  registry_class: string | null;
}

export interface ClinicalTrial {
  nct_id: string;
  title: string | null;
  status: string | null;
  phase: string | null;
  conditions: string[];
  interventions: string[];
  intervention_details: TrialIntervention[];
  collaborators: TrialCollaborator[];
  sponsor: string | null;
  study_type: string | null;
  url: string | null;
  // Raw registry values, preserved so the UI can show what the source said.
  overall_status: string | null;
  phases: string[];
  status_category: string | null;
  status_category_label: string | null;
  phase_category: string | null;
  ongoing: boolean;
  brief_summary: string | null;
  start_date: string | null;
  primary_completion_date: string | null;
  completion_date: string | null;
  enrollment_count: number | null;
  enrollment_type: string | null;
  last_update_date: string | null;
  source_url: string | null;
  retrieved_at: string | null;
}

export interface TrialRetrievalMetadata {
  query: string;
  retrieved_at: string | null;
  records_returned: number;
  total_available: number | null;
  has_more: boolean;
  partial: boolean;
  // False means the registry could not be consulted at all — not that it
  // reported no trials.
  source_reached: boolean;
  source: string;
  note: string | null;
}

export interface ChartBucket {
  label: string;
  count: number;
}

export interface StatusBucket extends ChartBucket {
  category: string;
}

export interface TrialStartPeriod {
  period: string;
  count: number;
}

export interface TrialAnalytics {
  total_trials: number;
  ongoing_trials: number;
  recruiting_trials: number;
  active_not_recruiting_trials: number;
  not_yet_recruiting_trials: number;
  completed_trials: number;
  discontinued_trials: number;
  paused_trials: number;
  other_status_trials: number;
  trials_with_unreported_phase: number;
  trials_by_phase: ChartBucket[];
  ongoing_trials_by_phase: ChartBucket[];
  trials_by_status: StatusBucket[];
  trial_starts_by_period: TrialStartPeriod[];
  timeline_granularity: string | null;
  timeline_omitted_reason: string | null;
  excluded_from_timeline_count: number;
  metadata: TrialRetrievalMetadata;
}

export interface CandidatePhaseBucket {
  phase: string;
  phase_category: string;
  trials: number;
  nct_ids: string[];
}

export interface CandidateRecord {
  name: string;
  matched_names: string[];
  intervention_types: string[];
  trials: number;
  nct_ids: string[];
  phases: CandidatePhaseBucket[];
  highest_phase: string | null;
  statuses: StatusBucket[];
  ongoing_trials: number;
  conditions: string[];
  sponsors: string[];
  collaborators: string[];
  // Taken from an openFDA label naming this product. openFDA labels name a
  // manufacturer and an application number, not an application holder, and
  // neither is ever a developer claim.
  fda_application_number: string | null;
  label_manufacturer: string | null;
  label_source_url: string | null;
  developer: string | null;
  developer_note: string;
  label_note: string;
  start_date: string | null;
  completion_date: string | null;
  last_update_date: string | null;
  retrieved_at: string | null;
  source_links: string[];
}

export interface CompanyPhaseCount {
  company: string;
  phase: string;
  candidates: number;
  attribution: string;
}

export interface CandidateAnalytics {
  distinct_candidates: number;
  candidate_trials_considered: number;
  trials_without_named_intervention: number;
  candidates_by_phase: ChartBucket[];
  ongoing_candidates_by_phase: ChartBucket[];
  candidates_by_company: ChartBucket[];
  company_by_phase: CompanyPhaseCount[];
  candidates_with_established_developer: number;
  candidates_with_openfda_label: number;
  comparator_candidates: number;
  non_drug_intervention_types: ChartBucket[];
  records: CandidateRecord[];
  counting_rule: string;
  metadata: TrialRetrievalMetadata;
}

/** What MolTel was asked to search for. Decided on the home page, shown in the
 *  header, and it determines which sources were queried at all. */
export type SearchMode = "compound" | "disease" | "target";

/** One disease concept exactly as the ontology names it. */
export interface DiseaseTerm {
  label: string;
  concept_id: string | null;
  ontology: string | null;
  url: string | null;
  iri: string | null;
  definition: string | null;
  synonyms: string[];
  /** The broader concept the ontology itself places this term under. */
  parent: string | null;
  parent_concept_id: string | null;
  excluded_synonyms: number;
}

/** A subtype with the retrieved records that name it. */
export interface DiseaseSubtype {
  label: string;
  /** "standardized concept", "registry condition wording", or "both". */
  origin: string;
  concept: DiseaseTerm | null;
  /** The subtype in this list whose name this one adds to, when one does. */
  refines: string | null;
  /** Whether that relation was read from the ontology or follows from wording. */
  refines_source: string | null;
  level: number;
  condition_labels: string[];
  trial_nct_ids: string[];
  candidate_names: string[];
  company_names: string[];
  paper_keys: string[];
  target_accessions: string[];
  availability_note: string;
}

export interface DiseaseAnalytics {
  query: string;
  canonical_term: string;
  canonical_term_provenance: string;
  concept: DiseaseTerm | null;
  synonyms: string[];
  subtypes: DiseaseSubtype[];
  /** Condition strings the retrieved trials name that no subtype above covers. */
  unmatched_condition_labels: ChartBucket[];
  trials_considered: number;
  trials_with_condition_label: number;
  trials_without_condition_label: number;
  papers_considered: number;
  targets_considered: number;
  candidates_considered: number;
  subtypes_with_records: number;
  subtypes_without_records: number;
  subtypes_omitted: number;
  ontology_reached: boolean;
  counting_rule: string;
  hierarchy_note: string;
  limitations: string[];
  metadata: TrialRetrievalMetadata | null;
}

export interface TrialsResponse {
  query: string;
  trials: ClinicalTrial[];
  metadata: TrialRetrievalMetadata;
  analytics: TrialAnalytics | null;
}

export interface EvidenceCategory {
  key: string;
  label: string;
  count: number;
  /** The rule MolTel used to place records here, stated by the backend. */
  criteria: string;
  records: string[];
}

export interface EvidenceStrength {
  categories: EvidenceCategory[];
  predominant_tier: string | null;
  interpretation: string | null;
  limitations: string[];
  unclassified_count: number;
  automated: boolean;
}

export interface Contradiction {
  claim: string | null;
  study_a: string | null;
  study_b: string | null;
  context_difference: string | null;
  possible_explanation: string | null;
  classification: string | null;
  confidence: string | null;
  missing_information: string | null;
  citations: string[];
}

export interface ContradictoryFindings {
  contradictions: Contradiction[];
  assessment: string | null;
  insufficient_evidence: boolean;
}

export interface ResearchGap {
  question: string | null;
  current_evidence: string | null;
  uncertainty: string | null;
  why_it_matters: string | null;
  next_step: string | null;
  confidence: string | null;
  label: string | null;
  references: string[];
}

export interface TargetProfile {
  accession: string;
  name: string | null;
  gene: string | null;
  organism: string | null;
  function_summary: string | null;
  subcellular_location: string | null;
  url: string | null;
}

export interface SourceStatus {
  source_name: string;
  /**
   * "skipped" means MolTel did not query this source for this search mode. It
   * is not a source failure and never makes the result partial on its own.
   */
  status: "success" | "error" | "no_results" | "skipped";
  count: number;
  error_message: string | null;
  note: string | null;
}

export interface Dossier {
  query: string;
  executive_summary: string | null;
  compound_profile: CompoundProfile | null;
  mechanism: string | null;
  therapeutic_evidence: string | null;
  literature_summary: string | null;
  clinical_development: string | null;
  safety: string | null;
  evidence_gaps: string | null;
  research_opportunities: string | null;
  contradictory_findings: ContradictoryFindings | null;
  research_gap_analysis: ResearchGap[];
  references: string[];
  sources_status: SourceStatus[];
}

export interface DossierResponse {
  query: string;
  status: "success" | "partial" | "error";
  search_mode: SearchMode;
  sources: SourceStatus[];
  dossier: Dossier | null;
  // False when the narrative sections were assembled from raw records because
  // AI synthesis was unavailable or failed to parse.
  ai_synthesized: boolean;
  synthesis_detail: string | null;
  // Raw structured data for tables
  evidence_items: EvidenceItem[];
  clinical_trials: ClinicalTrial[];
  targets: TargetProfile[];
  // Computed in the backend from the records above, never by the model.
  evidence_strength: EvidenceStrength | null;
  trial_analytics: TrialAnalytics | null;
  candidate_analytics: CandidateAnalytics | null;
  // Only for a disease search: the canonical term, synonyms and subtypes built
  // from the records above. A compound query has no subtype to resolve.
  disease_analytics: DiseaseAnalytics | null;
  // The literature ordering this response was built with. `items` is empty: the
  // ordered records are the literature subset of evidence_items.
  literature: LiteratureViewResult | null;
  retrieved_at: string | null;
}

// ─── Error type ───────────────────────────────────────────────────────────────

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly detail: string,
    message?: string
  ) {
    super(message ?? `API error ${status}: ${detail}`);
    this.name = "ApiError";
  }
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

async function handleResponse<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body?.detail ?? body?.error ?? JSON.stringify(body);
    } catch {
      // ignore JSON parse failure
    }
    throw new ApiError(res.status, detail);
  }
  return res.json() as Promise<T>;
}

// ─── API functions ────────────────────────────────────────────────────────────

/**
 * POST /api/dossier — generate a research dossier for the given query.
 * `mode` decides which sources are queried; it defaults to a compound search,
 * which is how the disease and target modes differ from it in what is asked.
 */
export async function fetchDossier(
  query: string,
  mode: SearchMode = "compound"
): Promise<DossierResponse> {
  const res = await fetch(`${API_BASE}/api/dossier`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query, search_mode: mode }),
  });
  return handleResponse<DossierResponse>(res);
}

/**
 * GET /api/compound/{name} — retrieve compound profile from PubChem.
 */
export async function fetchCompound(
  name: string
): Promise<CompoundProfile | null> {
  const res = await fetch(
    `${API_BASE}/api/compound/${encodeURIComponent(name)}`
  );
  if (res.status === 404) return null;
  return handleResponse<CompoundProfile>(res);
}

/**
 * GET /api/literature?query={query} — search both literature databases, merge
 * the records into publications and order them by one view's rule.
 */
export async function fetchLiterature(
  query: string,
  view: LiteratureView = "most_relevant"
): Promise<LiteratureViewResult> {
  const params = new URLSearchParams({ query, view });
  const res = await fetch(`${API_BASE}/api/literature?${params}`);
  return handleResponse<LiteratureViewResult>(res);
}

/**
 * POST /api/literature/views — re-order and filter records the page already
 * holds. No source is queried again, and the rule stays in the backend so the
 * browser never reimplements (or quietly diverges from) it.
 */
export async function requestLiteratureView(
  items: EvidenceItem[],
  query: string,
  view: LiteratureView,
  filters: LiteratureFilters = {}
): Promise<LiteratureViewResult> {
  const params = new URLSearchParams({ query, view });
  const res = await fetch(`${API_BASE}/api/literature/views?${params}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ items, query, view, filters }),
  });
  return handleResponse<LiteratureViewResult>(res);
}

/**
 * GET /api/trials?query={query} — retrieve clinical trials plus the
 * deterministic analytics for the landscape dashboard.
 */
export async function fetchTrials(query: string): Promise<TrialsResponse> {
  const params = new URLSearchParams({ query });
  const res = await fetch(`${API_BASE}/api/trials?${params}`);
  return handleResponse<TrialsResponse>(res);
}
