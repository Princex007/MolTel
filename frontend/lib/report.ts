/**
 * Shared report-data model.
 *
 * The dossier page, the PDF, the .docx, the printable HTML and the CSV exports
 * all read from this one model, so an export can never disagree with what the
 * dashboard shows. Every number here is computed in the backend from the
 * retrieved records; nothing in this file estimates, scores or invents.
 */

import type {
  CandidateAnalytics,
  CandidateRecord,
  ClinicalTrial,
  DiseaseAnalytics,
  DossierResponse,
  EvidenceItem,
  SearchMode,
  TargetProfile,
  TrialAnalytics,
} from "./api";
import { buildCandidateCharts } from "./candidateCharts";
import { buildTrialCharts, type ChartSpec } from "./trialCharts";

export const PRODUCT_NAME = "MolTel";

// ─── Node types ───────────────────────────────────────────────────────────────

export interface ReportTable {
  id: string;
  columns: string[];
  /** A cell that is a bare http(s) URL is rendered as a link by each exporter. */
  rows: string[][];
  note?: string;
  /** How many rows were left out of this document (they stay in the CSV export). */
  omittedRows?: number;
  totalRows?: number;
}

export type ReportNode =
  | { kind: "prose"; text: string }
  | { kind: "bullets"; items: string[] }
  | { kind: "callout"; tone: "warning" | "info" | "danger"; title: string; text: string }
  | { kind: "kv"; entries: [string, string][] }
  | { kind: "table"; table: ReportTable }
  | { kind: "charts"; charts: ChartSpec[] }
  | { kind: "references"; items: string[] };

export interface ReportSection {
  id: string;
  number: number;
  title: string;
  description?: string;
  nodes: ReportNode[];
}

export interface ReportModel {
  product: string;
  /** Display title, e.g. "ASPIRIN — Research Dossier". */
  title: string;
  query: string;
  statusLabel: string;
  aiSynthesized: boolean;
  synthesisDetail: string | null;
  /** When MolTel fetched the records, from the backend response. */
  retrievedAt: string | null;
  generatedAt: string;
  sections: ReportSection[];
  charts: ChartSpec[];
}

// ─── Small helpers ────────────────────────────────────────────────────────────

const MISSING = "Not reported by the source";

/** What each per-source status means, in the words the report uses. */
const SOURCE_STATUS_LABEL: Record<string, string> = {
  success: "queried, records returned",
  no_results: "queried, no records returned",
  error: "query failed",
  skipped: "not queried for this search mode",
};

export const SEARCH_MODE_LABEL: Record<SearchMode, string> = {
  compound: "compound or development code",
  disease: "disease or subtype",
  target: "target, gene or protein",
};

/**
 * The same statement in the few words a narrow PDF column can hold on one line.
 * Used inside composite cells (dates, links), where the long form would wrap the
 * value out of the cell.
 */
const MISSING_SHORT = "Not reported";

export function orMissing(value: string | number | null | undefined): string {
  if (value === null || value === undefined) return MISSING;
  const text = String(value).trim();
  return text === "" ? MISSING : text;
}

/** Split retrieved prose into list items the same way the on-page view does. */
export function toBullets(text: string): string[] {
  return text
    .split(/\n+/)
    .map((l) => l.replace(/^(?:[-•*]\s+|\d+[.)]\s+)/, "").trim())
    .filter(Boolean);
}

function proseOrBullets(text: string): ReportNode[] {
  const items = toBullets(text);
  if (items.length <= 1) return [{ kind: "prose", text: text.trim() }];
  return [{ kind: "bullets", items }];
}

export function identifierUrl(source: string, identifier: string | null): string | null {
  if (!identifier) return null;
  const s = source.toLowerCase();
  if (s.includes("pubmed")) return `https://pubmed.ncbi.nlm.nih.gov/${identifier}/`;
  if (s.includes("europe")) return `https://europepmc.org/article/med/${identifier}`;
  if (s.includes("clinicaltrials") || s.includes("ctgov"))
    return `https://clinicaltrials.gov/study/${identifier}`;
  if (s.includes("uniprot")) return `https://www.uniprot.org/uniprotkb/${identifier}`;
  if (s.includes("pubchem")) return `https://pubchem.ncbi.nlm.nih.gov/compound/${identifier}`;
  return null;
}

function fmtDate(value: string | null): string {
  if (!value) return MISSING;
  // Registry partial dates: 2020-07 or 2020. Keep them partial, do not invent a day.
  const parts = value.split("-");
  if (parts.length < 3) return value;
  return value;
}

function fmtDateTime(value: string | null): string {
  if (!value) return "unknown time";
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? value : d.toLocaleString();
}

// ─── Query-type signals (drive conditional sections, spec §3.1) ───────────────

export interface QuerySignals {
  compound: boolean;
  targets: boolean;
  disease: boolean;
}

export function detectSignals(data: DossierResponse): QuerySignals {
  const d = data.dossier;
  const conditions = new Set<string>();
  (data.clinical_trials ?? []).forEach((t) =>
    (t.conditions ?? []).forEach((c) => c && conditions.add(c.toLowerCase()))
  );
  return {
    compound: Boolean(d?.compound_profile?.name || d?.compound_profile?.cid),
    targets: (data.targets ?? []).length > 0 || Boolean(d?.mechanism),
    disease: conditions.size > 0 || Boolean(d?.therapeutic_evidence),
  };
}

// ─── Table builders ───────────────────────────────────────────────────────────

const PDF_ROW_CAP = 40;

function capRows(rows: string[][], cap: number): { rows: string[][]; omitted: number } {
  if (rows.length <= cap) return { rows, omitted: 0 };
  return { rows: rows.slice(0, cap), omitted: rows.length - cap };
}

export function literatureRows(items: EvidenceItem[]): string[][] {
  return items.map((it) => {
    const url = it.url || identifierUrl(it.source, it.id) || "";
    // Exactly the precision the source stated. A year is written as a year, not
    // padded into a date nobody reported.
    const published = it.published_on
      ? `${it.published_on}${it.published_precision && it.published_precision !== "day" ? ` (${it.published_precision})` : ""}`
      : it.year === null
        ? MISSING
        : String(it.year);
    return [
      orMissing(it.title),
      published,
      it.indexed_on ? `${it.indexed_on} (${it.indexed_field ?? "indexed"})` : "not reported",
      orMissing(it.source),
      evidenceTypeLabel(it.evidence_type),
      it.merged_records > 1
        ? `${it.merged_records} records (${it.merged_sources.join(", ")})`
        : "1 record",
      url || MISSING,
    ];
  });
}

/** Human wording for a source-stated evidence class, for report tables. */
export const EVIDENCE_TYPE_LABEL: Record<string, string> = {
  clinical: "Clinical study",
  randomized_controlled_trial: "Randomized controlled trial",
  systematic_review: "Systematic review / meta-analysis",
  observational: "Human observational study",
  case_report: "Case report / case series",
  animal: "Animal or in vivo study",
  cellular: "Cellular / in vitro study",
  biochemical: "Biochemical or structural study",
  computational: "Computational study",
  literature_review: "Narrative review",
  editorial: "Editorial / comment / letter",
  correction_or_retraction: "Correction or retraction notice",
  regulatory: "Regulatory label text",
  AI_hypothesis: "AI-generated hypothesis",
  other: "Not classified by the source",
};

export function evidenceTypeLabel(value: string | null | undefined): string {
  if (!value) return MISSING;
  return EVIDENCE_TYPE_LABEL[value] ?? value;
}

export function trialRows(trials: ClinicalTrial[]): string[][] {
  // Registry codes (PHASE1, COMPLETED) are kept in the CSV export; the report
  // table shows the label the dossier uses everywhere else.
  return trials.map((t) => [
    t.nct_id,
    orMissing(t.title),
    orMissing(t.phase ?? (t.phases?.length ? t.phases.join(" + ") : t.phase_category)),
    orMissing(t.status ?? t.overall_status),
    fmtDate(t.start_date),
    fmtDate(t.completion_date ?? t.primary_completion_date),
    orMissing(t.sponsor),
    t.source_url || `https://clinicaltrials.gov/study/${t.nct_id}`,
  ]);
}

export function targetRows(targets: TargetProfile[]): string[][] {
  return targets.map((t) => [
    orMissing(t.accession),
    orMissing(t.name),
    orMissing(t.gene),
    orMissing(t.organism),
    orMissing(t.function_summary),
    t.url || MISSING,
  ]);
}

export function regulatoryRows(items: EvidenceItem[]): string[][] {
  return items.map((it) => [
    orMissing(it.source),
    orMissing(it.title),
    String(it.metadata?.section ?? it.metadata?.effective_time ?? ""),
    orMissing(it.abstract ?? it.title),
    it.url || MISSING,
  ]);
}

// ─── Model builder ────────────────────────────────────────────────────────────

/** One row per subtype, in the order the backend lists them. */
export const DISEASE_SUBTYPE_COLUMNS = [
  "Subtype",
  "Where the name comes from",
  "Refines",
  "Relation source",
  "Trials",
  "Candidates",
  "Companies",
  "Papers",
  "Targets",
  "Condition wording carrying it",
  "Link",
] as const;

export function diseaseSubtypeRows(disease: DiseaseAnalytics): string[][] {
  return disease.subtypes.map((s) => [
    `${"  ".repeat(s.level)}${s.label}`,
    s.origin,
    s.refines ?? "",
    s.refines_source ?? "",
    String(s.trial_nct_ids.length),
    String(s.candidate_names.length),
    String(s.company_names.length),
    String(s.paper_keys.length),
    String(s.target_accessions.length),
    joinCapped(s.condition_labels, 3, ""),
    s.concept?.url ?? "",
  ]);
}

/**
 * Thirteen columns do not fit a portrait page, so the candidate records are
 * exported as two tables that share the candidate name and the same row order.
 * The CSV keeps every field in one row per candidate.
 */
export const CANDIDATE_COLUMNS_ID = [
  "Candidate",
  "Names as registered",
  "Indication(s)",
  "Phase(s)",
  "Registry status",
  "Trials",
] as const;

export const CANDIDATE_COLUMNS_ENTITY = [
  "Candidate",
  "Trial ID(s)",
  "Trial sponsor",
  "Company on a source record",
  "Developer",
  "Registry dates",
  "Registry link",
  "Label link",
] as const;

function joinCapped(values: string[], max: number, fallback: string): string {
  if (values.length === 0) return fallback;
  if (values.length <= max) return values.join("; ");
  return `${values.slice(0, max).join("; ")} +${values.length - max} more`;
}

function companyOnRecord(c: CandidateRecord): string {
  if (c.label_manufacturer) return `${c.label_manufacturer} (label manufacturer)`;
  if (c.fda_application_number) return `${c.fda_application_number} (application no.)`;
  return "No matched openFDA label";
}

/** Identity, phase and status for each candidate the registry names. */
export function candidateIdRows(candidates: CandidateRecord[]): string[][] {
  return candidates.map((c) => [
    c.name,
    joinCapped(c.matched_names, 2, MISSING),
    joinCapped(c.conditions, 2, "No condition text on these trials"),
    joinCapped(
      c.phases.map((p) => `${p.phase} (${p.trials})`),
      3,
      "Not reported"
    ),
    joinCapped(
      c.statuses.map((s) => `${s.label} (${s.count})`),
      3,
      "Not reported"
    ),
    String(c.trials),
  ]);
}

/**
 * The three entity claims a candidate can carry — sponsor, label manufacturer,
 * developer — kept in separate columns because they are three different claims.
 * The developer column only ever states what was searched.
 */
export function candidateEntityRows(candidates: CandidateRecord[]): string[][] {
  return candidates.map((c) => [
    c.name,
    joinCapped(c.nct_ids, 2, MISSING),
    joinCapped(c.sponsors, 2, "No sponsor recorded"),
    companyOnRecord(c),
    c.developer ?? "Developer not established",
    // Three short lines, not one long sentence: a narrow PDF column pushes the
    // value of a wrapped line off the bottom of the cell.
    `start ${c.start_date ?? MISSING_SHORT}\nest. completion ${c.completion_date ?? MISSING_SHORT}\nlast update ${c.last_update_date ?? MISSING_SHORT}`,
    // One URL per cell so each renders as a short labelled link, not a wrapped
    // address split mid-token. Every link is on the CSV row.
    c.source_links[0] ?? MISSING_SHORT,
    c.label_source_url ?? MISSING_SHORT,
  ]);
}

export function buildReportModel(data: DossierResponse, query: string): ReportModel {
  const d = data.dossier;
  const signals = detectSignals(data);
  const analytics: TrialAnalytics | null = data.trial_analytics ?? null;
  const candidates: CandidateAnalytics | null = data.candidate_analytics ?? null;
  const charts = analytics ? buildTrialCharts(analytics) : [];
  const candidateCharts = candidates ? buildCandidateCharts(candidates) : [];
  const sections: ReportSection[] = [];

  const push = (
    id: string,
    title: string,
    nodes: ReportNode[],
    description?: string
  ) => {
    if (nodes.length === 0) return;
    sections.push({ id, number: sections.length + 1, title, description, nodes });
  };

  // 1. Executive Summary — synthesis only; retrieval counts live in §9.
  const summaryNodes: ReportNode[] = [];
  if (d?.executive_summary && d.executive_summary.trim()) {
    summaryNodes.push(...proseOrBullets(d.executive_summary));
  } else {
    summaryNodes.push({
      kind: "callout",
      tone: "warning",
      title: "No AI synthesis available",
      text:
        (data.synthesis_detail ??
          "The interpretation layer was unavailable for this request.") +
        " The retrieved records, tables and charts below are complete and come straight from the source databases. No summary, contradiction comparison or gap analysis was produced, so none is asserted.",
    });
  }
  push("summary", "Executive Summary", summaryNodes);

  // 2. Disease Intelligence — for a disease search; otherwise the condition
  // wording the retrieved records carry, with no subtype claim made.
  const disease = data.disease_analytics;
  if (disease) {
    const nodes: ReportNode[] = [];
    if (data.ai_synthesized && d?.therapeutic_evidence?.trim()) {
      nodes.push(...proseOrBullets(d.therapeutic_evidence));
    }
    nodes.push({
      kind: "kv",
      entries: [
        ["Query as submitted", disease.query],
        ["Canonical disease term", disease.canonical_term],
        ["How that term was chosen", disease.canonical_term_provenance],
        [
          "Other names the same concept is recorded under",
          disease.synonyms.length ? disease.synonyms.join("; ") : "None recorded",
        ],
        [
          "Disease ontology",
          disease.ontology_reached
            ? "consulted for this query"
            : "could not be consulted — the subtype wording below is the condition wording the retrieved records themselves use",
        ],
        [
          "Records this view covers",
          `${disease.trials_considered} trials, ${disease.papers_considered} papers, ${disease.targets_considered} targets, ${disease.candidates_considered} candidates retrieved for this query`,
        ],
      ],
    });
    const { rows, omitted } = capRows(diseaseSubtypeRows(disease), PDF_ROW_CAP);
    nodes.push({
      kind: "table",
      table: {
        id: "subtypes",
        columns: [...DISEASE_SUBTYPE_COLUMNS],
        rows,
        omittedRows: omitted,
        totalRows: disease.subtypes.length,
        note: `Counts are the records in this retrieved set that carry the subtype wording. ${disease.subtypes_with_records} subtype(s) carry records and ${disease.subtypes_without_records} are named by the ontology or the registry alone${disease.subtypes_omitted ? `, and ${disease.subtypes_omitted} more were left off for length` : ""}.`,
      },
    });
    if (disease.subtypes_without_records > 0) {
      nodes.push({
        kind: "callout",
        tone: "info",
        title: "A subtype with no records here",
        text: "No retrieved record carries that wording. It says what this search fetched, not that research on the subtype is missing.",
      });
    }
    if (disease.unmatched_condition_labels.length) {
      nodes.push({
        kind: "kv",
        entries: [
          [
            "Other condition wording in the retrieved trials",
            disease.unmatched_condition_labels
              .map((b) => `${b.label} (${b.count})`)
              .join("; "),
          ],
        ],
      });
    }
    if (disease.limitations.length) {
      nodes.push({ kind: "bullets", items: disease.limitations });
    }
    nodes.push({ kind: "prose", text: disease.counting_rule });
    nodes.push({ kind: "prose", text: disease.hierarchy_note });
    push(
      "disease",
      `Disease Intelligence — ${disease.canonical_term}`,
      nodes,
      "Subtype choices come from standardized disease concepts and from the condition wording of the retrieved records, not from a fixed list of diseases. The query is kept exactly as submitted."
    );
  }

  if (!disease && signals.disease) {
    const nodes: ReportNode[] = [];
    if (d?.therapeutic_evidence?.trim()) {
      nodes.push(...proseOrBullets(d.therapeutic_evidence));
    }
    const conditions = Array.from(
      new Set((data.clinical_trials ?? []).flatMap((t) => t.conditions ?? []))
    ).slice(0, 30);
    if (conditions.length) {
      nodes.push({
        kind: "kv",
        entries: [
          [
            "Condition terms reported by the retrieved trials",
            conditions.join("; "),
          ],
          [
            "Disease subtype refinement",
            "Not applied — these records were retrieved with the query as written. Subtype filtering is listed under Limitations.",
          ],
        ],
      });
    }
    push(
      "disease-context",
      "Disease and Therapeutic Context",
      nodes,
      "Condition terms and therapeutic statements taken from the retrieved records."
    );
  }

  // 3. Compound Profile — only for compound queries.
  if (signals.compound && d?.compound_profile) {
    const c = d.compound_profile;
    push("compound", "Compound Profile", [
      {
        kind: "kv",
        entries: [
          ["Name", orMissing(c.name)],
          ["PubChem CID", orMissing(c.cid)],
          ["Molecular formula", orMissing(c.molecular_formula)],
          ["Molecular weight", orMissing(c.molecular_weight)],
          ["Canonical SMILES", orMissing(c.canonical_smiles)],
          ["Isomeric SMILES", orMissing(c.isomeric_smiles)],
          ["IUPAC name", orMissing(c.iupac_name)],
          ["InChIKey", orMissing(c.inchi_key)],
          [
            "Synonyms",
            c.synonyms && c.synonyms.length
              ? c.synonyms.slice(0, 12).join("; ")
              : MISSING,
          ],
          ["Source", "PubChem, retrieved " + fmtDateTime(data.retrieved_at)],
        ],
      },
    ]);
  }

  // 4. Mechanism and Target Biology
  const mechNodes: ReportNode[] = [];
  if (d?.mechanism?.trim()) mechNodes.push(...proseOrBullets(d.mechanism));
  if ((data.targets ?? []).length) {
    const { rows, omitted } = capRows(targetRows(data.targets), PDF_ROW_CAP);
    mechNodes.push({
      kind: "table",
      table: {
        id: "targets",
        columns: ["Accession", "Name", "Gene", "Organism", "Function", "Link"],
        rows,
        omittedRows: omitted,
        totalRows: data.targets.length,
        note: "UniProt records retrieved for this query. Function text is the source summary, truncated for layout.",
      },
    });
  }
  if (mechNodes.length) {
    push(
      "mechanism",
      "Mechanism and Target Biology",
      mechNodes,
      "Target statements from UniProt and the retrieved literature."
    );
  }

  // 5. Literature Evidence
  const litNodes: ReportNode[] = [];
  if (d?.literature_summary?.trim()) litNodes.push(...proseOrBullets(d.literature_summary));
  if (data.evidence_strength) {
    const es = data.evidence_strength;
    litNodes.push({
      kind: "table",
      table: {
        id: "evidence-classes",
        columns: ["Evidence class", "Records", "Classification basis"],
        rows: es.categories.map((c) => [
          c.label,
          String(c.count),
          "Assigned by the retrieval pipeline from source record metadata (publication type and study descriptors), not judged by the model.",
        ]),
        note:
          (es.unclassified_count > 0
            ? `${es.unclassified_count} record(s) could not be classified from their source metadata and are reported as unclassified rather than forced into a class. `
            : "") +
          "Publication type is not a quality score: no numeric evidence score is computed and none is implied.",
      },
    });
    if (es.interpretation?.trim()) {
      litNodes.push({ kind: "prose", text: es.interpretation.trim() });
    }
  }
  const litItems = (data.evidence_items ?? []).filter((i) => i.source_type === "literature");
  if (litItems.length) {
    const { rows, omitted } = capRows(literatureRows(litItems), PDF_ROW_CAP);
    litNodes.push({
      kind: "table",
      table: {
        id: "literature",
        columns: [
          "Title",
          "Published",
          "Indexed",
          "Source",
          "Evidence type",
          "Records merged",
          "Link",
        ],
        rows,
        omittedRows: omitted,
        totalRows: litItems.length,
        note:
          `${litItems.length} publication(s) retrieved${
            omitted > 0
              ? `; the first ${PDF_ROW_CAP} are listed here and all ${litItems.length} are in the CSV export`
              : ""
          }. ${
            data.literature?.deduplication
              ? `Built from ${data.literature.deduplication.records_received} record(s) merged on ${data.literature.deduplication.matched_on.join(", ")}. `
              : ""
          }Ordered as retrieved. 'Published' is the source's own publication date at the precision it stated; 'Indexed' is when the database indexed the record and is not a publication date.`,
      },
    });
  }
  if (litNodes.length) push("literature", "Literature Evidence", litNodes);

  // 6. Clinical Development — the only place trial counts appear.
  const clNodes: ReportNode[] = [];
  if (analytics) {
    clNodes.push({
      kind: "kv",
      entries: [
        ["Distinct trials retrieved", String(analytics.total_trials)],
        ["Recruiting", String(analytics.recruiting_trials)],
        ["Active, not recruiting", String(analytics.active_not_recruiting_trials)],
        ["Not yet recruiting", String(analytics.not_yet_recruiting_trials)],
        ["Completed", String(analytics.completed_trials)],
        ["Discontinued (terminated or withdrawn)", String(analytics.discontinued_trials)],
        ["Suspended", String(analytics.paused_trials)],
        ["Other or unclear status", String(analytics.other_status_trials)],
        ["Ongoing (Recruiting + Active, not recruiting)", String(analytics.ongoing_trials)],
        ["Phase not reported", String(analytics.trials_with_unreported_phase)],
      ],
    });
    clNodes.push({
      kind: "prose",
      text:
        "These status rows are one record per trial and sum to the distinct total; Ongoing and phase-not-reported are re-cuts of the same records and are never added to them. A completed trial is not necessarily a successful one, and recruiting does not establish efficacy.",
    });
    if (d?.clinical_development?.trim()) {
      clNodes.push(...proseOrBullets(d.clinical_development));
    }
    clNodes.push({ kind: "charts", charts });
    const { rows, omitted } = capRows(trialRows(data.clinical_trials ?? []), PDF_ROW_CAP);
    clNodes.push({
      kind: "table",
      table: {
        id: "trials",
        columns: [
          "NCT ID",
          "Title",
          "Phase",
          "Registry status",
          "Start",
          "Completion",
          "Sponsor",
          "Link",
        ],
        rows,
        omittedRows: omitted,
        totalRows: (data.clinical_trials ?? []).length,
        note:
          `Registry values as reported by ClinicalTrials.gov on ${fmtDateTime(
            analytics.metadata.retrieved_at
          )}. Phase and status are separate dimensions; combined phases stay one category. ` +
          (omitted > 0
            ? `The first ${PDF_ROW_CAP} of ${rows.length + omitted} trials are listed here; all are in the CSV export.`
            : "This table is the authoritative record list for the counts above."),
      },
    });
    if (candidates) {
      clNodes.push({
        kind: "prose",
        text:
          `Candidate-level view: ${candidates.distinct_candidates} distinct product candidate(s) are named as interventions in ` +
          `${candidates.candidate_trials_considered} of ${analytics.total_trials} distinct trials. ` +
          `${candidates.counting_rule} ` +
          `Placebo or sham comparators that the registry types as drug interventions account for ` +
          `${candidates.comparator_candidates} of these names; they are listed because a source names them, ` +
          `not because MolTel treats them as candidates in development. ` +
          `${candidates.candidates_with_established_developer} candidate(s) have a developer a retrieved source states; ` +
          `${candidates.candidates_with_openfda_label} match an openFDA label, which names a manufacturer and an application number rather than an application holder. Neither is treated as a developer here.`,
      });
      clNodes.push({ kind: "charts", charts: candidateCharts });
      const shown = candidates.records.slice(0, PDF_ROW_CAP);
      const omitted = candidates.records.length - shown.length;
      const listNote = (what: string) =>
        `One row per product name the registry lists as a drug, biological, dietary supplement or ` +
        `combination-product intervention${what}. ${candidates.trials_without_named_intervention} retrieved ` +
        `trial(s) name no such intervention and are not represented here. ` +
        (omitted > 0
          ? `The first ${PDF_ROW_CAP} of ${candidates.records.length} candidates are listed here; all are in the CSV export, ` +
            `where every field sits on one row.`
          : "Every candidate in this set is listed.");
      clNodes.push({
        kind: "table",
        table: {
          id: "candidates-identification",
          columns: [...CANDIDATE_COLUMNS_ID],
          rows: candidateIdRows(shown),
          omittedRows: omitted,
          totalRows: candidates.records.length,
          note:
            listNote(" (identity, indications, phases and registry statuses)") +
            " Both candidate tables share this row order and the candidate name, so a row here pairs with the row of the same name in the next table.",
        },
      });
      clNodes.push({
        kind: "table",
        table: {
          id: "candidates-entities",
          columns: [...CANDIDATE_COLUMNS_ENTITY],
          rows: candidateEntityRows(shown),
          omittedRows: omitted,
          totalRows: candidates.records.length,
          note:
            listNote(" (sponsor, label record, developer and dates)") +
            " Sponsor, label manufacturer and developer are separate columns: a sponsor or a label manufacturer is never reported as a developer.",
        },
      });
    }
    push(
      "clinical",
      "Clinical Development",
      clNodes,
      `Computed from ${analytics.metadata.records_returned} deduplicated ${analytics.metadata.source} record(s) retrieved ${fmtDateTime(
        analytics.metadata.retrieved_at
      )}. This is the retrieved set, not the whole registry.`
    );
  } else if ((data.clinical_trials ?? []).length) {
    clNodes.push({
      kind: "callout",
      tone: "danger",
      title: "Registry not consulted",
      text:
        "ClinicalTrials.gov could not be reached for this query, so no counts or charts are shown. Listing them as zero would claim the registry has nothing, which was not established.",
    });
    push("clinical", "Clinical Development", clNodes);
  }

  // 7. Safety and Regulatory Intelligence
  const safeNodes: ReportNode[] = [];
  if (d?.safety?.trim()) safeNodes.push(...proseOrBullets(d.safety));
  const regItems = (data.evidence_items ?? []).filter((i) => i.source_type === "regulatory");
  if (regItems.length) {
    const { rows, omitted } = capRows(regulatoryRows(regItems), PDF_ROW_CAP);
    safeNodes.push({
      kind: "table",
      table: {
        id: "regulatory",
        columns: ["Source", "Product / label", "Section", "Statement", "Link"],
        rows,
        omittedRows: omitted,
        totalRows: regItems.length,
        note:
          "Label text is quoted from the source and equivalent passages are consolidated; distinct formulations and label sources are kept apart. " +
          (omitted > 0 ? `All ${regItems.length} passages are in the CSV export.` : ""),
      },
    });
  }
  if (safeNodes.length) {
    push(
      "safety",
      "Safety and Regulatory Intelligence",
      safeNodes,
      "Retrieved label passages and regulatory records, with their sources."
    );
  }

  // 8. Potential Research Opportunities
  const oppNodes: ReportNode[] = [];
  if (data.ai_synthesized && d?.contradictory_findings) {
    const cf = d.contradictory_findings;
    if (cf.contradictions.length) {
      oppNodes.push({
        kind: "table",
        table: {
          id: "contradictions",
          columns: ["Claim in tension", "Study A", "Study B", "Explanation", "Confidence", "Citations"],
          rows: cf.contradictions.map((c) => [
            orMissing(c.claim),
            orMissing(c.study_a),
            orMissing(c.study_b),
            orMissing(c.possible_explanation ?? c.context_difference),
            orMissing(c.confidence),
            (c.citations ?? []).join("; "),
          ]),
        },
      });
    } else {
      oppNodes.push({
        kind: "prose",
        text:
          cf.assessment?.trim() ||
          "No clear contradiction was identified in the retrieved evidence. This does not establish that conflicting evidence does not exist.",
      });
    }
  } else if (!data.ai_synthesized) {
    oppNodes.push({
      kind: "callout",
      tone: "info",
      title: "Contradiction comparison not performed",
      text: "AI synthesis was unavailable, so no comparison of conflicting claims was made. Nothing here should be read as evidence that findings agree.",
    });
  }
  const gaps = d?.research_gap_analysis ?? [];
  if (gaps.length) {
    oppNodes.push({
      kind: "table",
      table: {
        id: "gaps",
        columns: ["Potential research gap in the retrieved evidence", "Current evidence", "Uncertainty", "Suggested next step", "Confidence"],
        rows: gaps.map((g) => [
          orMissing(g.question),
          orMissing(g.current_evidence),
          orMissing(g.uncertainty),
          orMissing(g.next_step),
          orMissing(g.confidence ?? g.label),
        ]),
        note: "Labelled as potential gaps in the retrieved evidence — not proof that a question is unstudied.",
      },
    });
  } else if (data.ai_synthesized) {
    oppNodes.push({
      kind: "prose",
      text: "No specific unanswered question stood out in the retrieved evidence. This is a statement about these records, not about the literature as a whole.",
    });
  }
  if (d?.research_opportunities?.trim()) {
    oppNodes.push({
      kind: "callout",
      tone: "warning",
      title: "AI-generated hypotheses",
      text: "Speculative research directions, not established science. Verify independently before acting on them.",
    });
    oppNodes.push(...proseOrBullets(d.research_opportunities));
  }
  if (oppNodes.length) push("opportunities", "Potential Research Opportunities", oppNodes);

  // 9. Sources, Retrieval Metadata and Limitations
  const registryUpdates = (data.clinical_trials ?? [])
    .map((t) => t.last_update_date)
    .filter((v): v is string => Boolean(v))
    .sort();
  const srcNodes: ReportNode[] = [
    {
      kind: "table",
      table: {
        id: "sources",
        columns: ["Source", "Status", "Records", "Detail"],
        rows: data.sources.map((s) => [
          s.source_name,
          SOURCE_STATUS_LABEL[s.status] ?? s.status,
          String(s.count),
          s.error_message ?? s.note ?? "",
        ]),
        note:
          "Each source is retrieved independently; one failure does not invalidate the others. A source marked not queried was not asked for this search mode, which is not a failure and not an empty result.",
      },
    },
    {
      kind: "kv",
      entries: [
        ["Query as submitted", query],
        [
          "Searched as",
          SEARCH_MODE_LABEL[data.search_mode ?? "compound"],
        ],
        ["MolTel retrieval time", fmtDateTime(data.retrieved_at)],
        ["Registry retrieval time", analytics ? fmtDateTime(analytics.metadata.retrieved_at) : MISSING],
        [
          "Registry last-update dates (a source fact, not a MolTel timestamp)",
          registryUpdates.length
            ? `Newest ${registryUpdates[registryUpdates.length - 1]}, oldest ${registryUpdates[0]} across ${registryUpdates.length} of ${
                (data.clinical_trials ?? []).length
              } trials; ${
                (data.clinical_trials ?? []).length - registryUpdates.length
              } trial(s) reported no last-update date.`
            : MISSING,
        ],
        ["Document generated", new Date().toLocaleString()],
        ["Retrieval scope", analytics ? `${analytics.metadata.records_returned} deduplicated records returned${analytics.metadata.has_more ? " (the registry reported that more match the query)" : ""}` : "ClinicalTrials.gov analytics unavailable"],
        ["Interpretation layer", data.ai_synthesized ? "OpenRouter synthesis succeeded" : `AI synthesis unavailable — ${data.synthesis_detail ?? "no detail reported"}`],
      ],
    },
  ];
  if (d?.evidence_gaps?.trim()) srcNodes.push(...proseOrBullets(d.evidence_gaps));
  srcNodes.push({
    kind: "callout",
    tone: "info",
    title: "Scope of this report",
    text: "This dossier describes the records MolTel retrieved for this query. It does not claim to cover every publication or registered trial that exists, and completed status or a recruiting count is not evidence of efficacy.",
  });
  if (d?.references?.length) {
    srcNodes.push({ kind: "references", items: d.references });
  }
  push(
    "sources",
    "Sources, Retrieval Metadata and Limitations",
    srcNodes
  );

  const displayName = d?.compound_profile?.name ?? query;

  return {
    product: PRODUCT_NAME,
    title: `${displayName.toUpperCase()} — Research Dossier`,
    query,
    statusLabel: data.status === "success" ? "Complete" : data.status === "partial" ? "Partial" : "Error",
    aiSynthesized: data.ai_synthesized,
    synthesisDetail: data.synthesis_detail,
    retrievedAt: data.retrieved_at,
    generatedAt: new Date().toISOString(),
    sections,
    charts: [...charts, ...candidateCharts],
  };
}

// ─── Filenames ────────────────────────────────────────────────────────────────

export function reportFileName(query: string, extension: string): string {
  const slug =
    query
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "")
      .slice(0, 48) || "dossier";
  const stamp = new Date().toISOString().slice(0, 10);
  return `moltel-${slug}-${stamp}.${extension}`;
}

export type { ChartSpec };
