/**
 * Structured data export (CSV) for the record lists behind the dossier.
 *
 * CSV is what a reader takes to a spreadsheet; the narrative report stays in
 * PDF and Word. Cells are quoted so commas, quotes and label text survive an
 * Excel import, and a UTF-8 BOM keeps accented titles readable there.
 */

import type { DossierResponse, EvidenceItem } from "../api";
import { SEARCH_MODE_LABEL, evidenceTypeLabel } from "../report";

/**
 * CSV keeps the machine-readable columns a spreadsheet reader needs: the value
 * the source reported, MolTel's normalization of it, and the identifiers, in
 * separate columns. The narrative report (PDF/Word/print) shows labels instead.
 */
export type Dataset =
  | "trials"
  | "candidates"
  | "publications"
  | "regulatory"
  | "targets"
  | "subtypes";

function text(value: unknown): string {
  if (value === null || value === undefined) return "";
  return String(value);
}

function meta(item: EvidenceItem, key: string): string {
  const value = (item.metadata ?? {})[key];
  if (Array.isArray(value)) return value.filter(Boolean).join("; ");
  return text(value);
}

const DATASETS: Record<
  Dataset,
  { label: string; columns: string[]; build: (d: DossierResponse) => string[][] }
> = {
  trials: {
    label: "Trial records (ClinicalTrials.gov)",
    columns: [
      "nct_id",
      "title_as_registered",
      "phase_as_registered",
      "phases_reported_by_registry",
      "status_as_registered",
      "moltel_status_grouping",
      "ongoing_by_moltel_definition",
      "study_type",
      "conditions",
      "interventions",
      "intervention_types_as_registered",
      "sponsor",
      "collaborators_and_their_registry_class",
      "start_date",
      "primary_completion_date",
      "completion_date",
      "enrollment_count",
      "enrollment_type",
      "last_update_date_by_registry",
      "moltel_retrieved_at",
      "source_url",
    ],
    build: (d) =>
      (d.clinical_trials ?? []).map((t) => [
        t.nct_id,
        text(t.title),
        text(t.phase),
        (t.phases ?? []).join("; "),
        text(t.overall_status),
        text(t.status_category_label ?? t.status_category),
        t.ongoing ? "yes" : "no",
        text(t.study_type),
        (t.conditions ?? []).join("; "),
        (t.interventions ?? []).join("; "),
        (t.intervention_details ?? [])
          .map(
            (i) =>
              `${i.name} [${i.type ?? "type not reported"}${
                i.role ? `, arm role ${i.role}` : ", arm role not reported"
              }]`
          )
          .join("; ") || "none reported",
        text(t.sponsor),
        (t.collaborators ?? [])
          .map((c) => `${c.name} [${c.registry_class ?? "class not reported"}]`)
          .join("; ") || "none reported",
        text(t.start_date),
        text(t.primary_completion_date),
        text(t.completion_date),
        text(t.enrollment_count),
        text(t.enrollment_type),
        text(t.last_update_date),
        text(t.retrieved_at ?? d.retrieved_at),
        t.source_url || `https://clinicaltrials.gov/study/${t.nct_id}`,
      ]),
  },
  candidates: {
    label: "Candidate products named in trials",
    columns: [
      "candidate_name",
      "names_as_registered",
      "intervention_types_as_registered",
      "trials_naming_this_candidate",
      "nct_ids",
      "phases_as_registered",
      "statuses_as_registered",
      "ongoing_trials",
      "highest_phase_reached",
      "trial_sponsors",
      "registry_collaborators",
      "openfda_label_manufacturer",
      "openfda_application_number",
      "openfda_label_url",
      "developer",
      "developer_note",
      "conditions",
      "earliest_start",
      "latest_completion",
      "last_registry_update",
      "moltel_retrieved_at",
      "source_urls",
    ],
    build: (d) =>
      (d.candidate_analytics?.records ?? []).map((c) => [
        c.name,
        c.matched_names.join("; "),
        c.intervention_types.join("; "),
        String(c.trials),
        c.nct_ids.join("; "),
        c.phases.map((p) => `${p.phase} (${p.trials} trial(s): ${p.nct_ids.join(", ")})`).join("; "),
        c.statuses.map((s) => `${s.label} (${s.count})`).join("; "),
        String(c.ongoing_trials),
        c.highest_phase ?? "No clinical phase reported",
        c.sponsors.join("; ") || "none reported",
        c.collaborators.join("; ") || "none reported",
        c.label_manufacturer ?? "no openFDA label matched this name",
        c.fda_application_number ?? "",
        c.label_source_url ?? "",
        // Sponsorship and label manufacture are not development; this stays blank
        // unless a retrieved source states a developer.
        c.developer ?? "",
        c.developer_note,
        c.conditions.join("; "),
        c.start_date ?? "",
        c.completion_date ?? "",
        c.last_update_date ?? "",
        c.retrieved_at ?? "",
        c.source_links.join(" "),
      ]),
  },
  publications: {
    label: "Publication records",
    columns: [
      "source",
      "title",
      "journal",
      "year",
      "published_date_as_stated",
      "published_date_precision",
      "indexed_date_as_stated",
      "indexed_date_field",
      "authors",
      "publication_types_reported_by_source",
      "moltel_evidence_class",
      "open_access_as_stated",
      "pmid",
      "pmcid",
      "doi",
      "record_id",
      "records_merged_into_this_publication",
      "merged_from_sources",
      "all_source_links",
      "moltel_relevance_ordering_key",
      "url",
      "moltel_retrieved_at",
    ],
    build: (d) =>
      (d.evidence_items ?? [])
        .filter((i) => i.source_type === "literature")
        .map((it) => [
          text(it.source),
          text(it.title),
          it.journal ?? meta(it, "journal"),
          text(it.year),
          text(it.published_on),
          text(it.published_precision),
          text(it.indexed_on),
          text(it.indexed_field),
          (it.authors ?? []).join("; "),
          it.publication_types?.join("; ") ||
            meta(it, "publication_types") ||
            "none reported",
          evidenceTypeLabel(it.evidence_type),
          it.open_access === true
            ? "stated open access"
            : it.open_access === false
              ? "stated not open access"
              : "not stated by the source",
          text(it.pmid),
          text(it.pmcid),
          text(it.doi),
          text(it.id),
          text(it.merged_records ?? 1),
          (it.merged_sources ?? []).join("; "),
          (it.links ?? []).join(" "),
          text(it.relevance_score),
          text(it.url),
          text(d.retrieved_at),
        ]),
  },
  regulatory: {
    label: "Regulatory label passages",
    columns: [
      "source",
      "product_or_application",
      "section_code",
      "section_title",
      "statement_as_published",
      "label_effective_time",
      "moltel_retrieved_at",
      "url",
    ],
    build: (d) =>
      (d.evidence_items ?? [])
        .filter((i) => i.source_type === "regulatory")
        .map((it) => [
          text(it.source),
          meta(it, "application_number") || meta(it, "product") || text(it.title),
          meta(it, "section"),
          meta(it, "section_title"),
          text(it.abstract ?? it.title),
          meta(it, "effective_time"),
          text(d.retrieved_at),
          text(it.url),
        ]),
  },
  targets: {
    label: "Protein target records (UniProt)",
    columns: [
      "accession",
      "name",
      "gene",
      "organism",
      "function_as_reported",
      "subcellular_location_as_reported",
      "moltel_retrieved_at",
      "url",
    ],
    build: (d) =>
      (d.targets ?? []).map((t) => [
        text(t.accession),
        text(t.name),
        text(t.gene),
        text(t.organism),
        text(t.function_summary),
        text(t.subcellular_location),
        text(d.retrieved_at),
        text(t.url),
      ]),
  },
  subtypes: {
    label: "Disease subtypes (disease search)",
    columns: [
      "subtype",
      "level",
      "where_the_name_comes_from",
      "refines",
      "relation_source",
      "concept_id",
      "ontology",
      "trials",
      "trial_nct_ids",
      "candidates",
      "candidate_names",
      "companies_on_those_trials",
      "papers",
      "targets",
      "target_accessions",
      "condition_wording_carrying_it",
      "availability_note",
      "concept_url",
    ],
    build: (d) =>
      (d.disease_analytics?.subtypes ?? []).map((s) => [
        s.label,
        String(s.level),
        s.origin,
        s.refines ?? "",
        s.refines_source ?? "",
        s.concept?.concept_id ?? "",
        s.concept?.ontology ?? "",
        String(s.trial_nct_ids.length),
        s.trial_nct_ids.join("; "),
        String(s.candidate_names.length),
        s.candidate_names.join("; "),
        s.company_names.join("; "),
        String(s.paper_keys.length),
        String(s.target_accessions.length),
        s.target_accessions.join("; "),
        s.condition_labels.join("; "),
        s.availability_note,
        s.concept?.url ?? "",
      ]),
  },
};

export const DATASET_OPTIONS: { value: Dataset; label: string }[] = (
  Object.keys(DATASETS) as Dataset[]
)
  .filter((value) => value !== "subtypes")
  .map((value) => ({ value, label: DATASETS[value].label }));

/** The lists this response actually has. Subtypes only exist for a disease search. */
export function datasetOptions(data: DossierResponse): { value: Dataset; label: string }[] {
  const options = [...DATASET_OPTIONS];
  if (data.disease_analytics) {
    options.splice(1, 0, { value: "subtypes", label: DATASETS.subtypes.label });
  }
  return options;
}

function metaLines(dataset: Dataset, data: DossierResponse, query: string): string[] {
  const retrieved = data.trial_analytics?.metadata.retrieved_at ?? data.retrieved_at;
  const lines = [
    `# MolTel data export — ${DATASETS[dataset].label}`,
    `# Query: ${query.replace(/[\r\n]/g, " ")}`,
    `# Searched as: ${SEARCH_MODE_LABEL[data.search_mode ?? "compound"]}`,
    `# Retrieval time: ${retrieved ?? "unknown"}`,
    `# Generated: ${new Date().toISOString()}`,
  ];
  if (dataset === "trials" && data.trial_analytics) {
    const a = data.trial_analytics;
    lines.push(
      `# Scope: ${a.metadata.records_returned} deduplicated records retrieved by MolTel — this is the retrieved set, not every trial in the registry.`
    );
    lines.push(
      `# Phase and status are separate dimensions. Combined phases stay one category. Statuses are the registry's own labels.`
    );
  }
  if (dataset === "candidates" && data.candidate_analytics) {
    const c = data.candidate_analytics;
    lines.push(
      `# Scope: ${c.distinct_candidates} distinct candidate product name(s) drawn from ${c.candidate_trials_considered} of ${c.metadata.records_returned} retrieved trial records. ${c.trials_without_named_intervention} trial(s) name no drug, biological, dietary supplement or combination product.`
    );
    lines.push(
      `# ${c.counting_rule} Trial, sponsor, label manufacturer and developer are separate columns; a developer is only filled when a retrieved source states one, and openFDA labels name a manufacturer and application number, not an application holder.`
    );
  }
  if (dataset === "publications") {
    const lit = (data.evidence_items ?? []).filter((i) => i.source_type === "literature").length;
    const dedup = data.literature?.deduplication ?? null;
    lines.push(
      `# Scope: ${lit} publication(s) retrieved by MolTel${
        dedup
          ? `, built from ${dedup.records_received} record(s) merged on ${dedup.matched_on.join(", ")} (${dedup.records_merged} record(s) folded into another, ${dedup.cross_database_merges} merge(s) spanning both databases). This is the retrieved set, not the whole literature.`
          : " — this is the retrieved set, not the whole literature."
      }`
    );
    lines.push(
      `# 'publication_types_reported_by_source' is what the source attached to the record; 'moltel_evidence_class' is MolTel's reading of it. Unclassified records say so.`
    );
    lines.push(
      `# 'published_date_as_stated' is the source's publication date at the precision it stated ('published_date_precision' gives that precision). 'indexed_date_as_stated' is when the database indexed the record and is never a publication date. 'moltel_relevance_ordering_key' orders the most-relevant list; it is not a quality score, and no quality score is computed.`
    );
  }
  if (dataset === "targets") {
    lines.push(
      `# Scope: ${(data.targets ?? []).length} UniProt record(s) returned for this query. A returned record is not by itself evidence that the protein is the relevant target.`
    );
  }
  if (dataset === "regulatory") {
    lines.push(
      `# Scope: label passages quoted as published by the source. Statements on a label are spontaneous reports and are not proof of causality.`
    );
  }
  if (dataset === "subtypes" && data.disease_analytics) {
    const g = data.disease_analytics;
    lines.push(
      `# Canonical term: ${g.canonical_term} — ${g.canonical_term_provenance.replace(/[\r\n]/g, " ")}`
    );
    lines.push(
      `# Scope: ${g.trials_considered} trial record(s), ${g.papers_considered} paper(s), ${g.targets_considered} target(s) and ${g.candidates_considered} candidate(s) retrieved for this query. A subtype with no records here means none were retrieved, not that none exist.`
    );
    lines.push(
      `# ${g.counting_rule.replace(/[\r\n]/g, " ")}`
    );
    lines.push(`# ${g.hierarchy_note.replace(/[\r\n]/g, " ")}`);
  }
  return lines;
}

function csvCell(value: unknown): string {
  const cell = String(value ?? "");
  if (/[",\r\n]/.test(cell) || cell.trim() !== cell) {
    return `"${cell.replace(/"/g, '""')}"`;
  }
  return cell;
}

export function buildCsv(data: DossierResponse, query: string, dataset: Dataset): string {
  const rows = DATASETS[dataset].build(data);
  const lines = [...metaLines(dataset, data, query)];
  lines.push(DATASETS[dataset].columns.map(csvCell).join(","));
  for (const row of rows) lines.push(row.map(csvCell).join(","));
  return "\uFEFF" + lines.join("\r\n") + "\r\n";
}

export function csvFileName(query: string, dataset: Dataset): string {
  const slug =
    query
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "")
      .slice(0, 40) || "dossier";
  return `moltel-${slug}-${dataset}-${new Date().toISOString().slice(0, 10)}.csv`;
}
