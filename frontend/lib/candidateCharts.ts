/**
 * Chart specifications for the candidate-level view (spec §5.2).
 *
 * These count products named as registry interventions, not studies, and the
 * subtitles say so. Every number comes from the backend's deterministic pass
 * over the same deduplicated trial list the table beside it uses.
 */

import type { CandidateAnalytics, ChartBucket } from "./api";
import { colorForPhase, colorForSeries } from "./chartColors";
import type { ChartSpec } from "./trialCharts";

const COMPANY_CAP = 12;

function phaseSeries(buckets: ChartBucket[]): ChartSpec["data"] {
  return buckets.map((b) => ({ label: b.label, value: b.count, color: colorForPhase(b.label) }));
}

export function buildCandidateCharts(c: CandidateAnalytics): ChartSpec[] {
  const phaseSum = c.candidates_by_phase.reduce((s, b) => s + b.count, 0);

  const byPhase: ChartSpec = {
    id: "candidates-by-phase",
    title: "Distinct candidates by phase",
    subtitle: `Counts drug, biological, dietary-supplement and combination-product names the registry lists as interventions — candidates, not studies. ${c.distinct_candidates} distinct candidate${
      c.distinct_candidates === 1 ? "" : "s"
    } appear across ${phaseSum} candidate-phase pairs, so a product studied in more than one phase is counted once in each of those phases. ${c.counting_rule}`,
    unit: "distinct candidates",
    kind: "bar",
    data: phaseSeries(c.candidates_by_phase),
    emptyNote:
      c.candidate_trials_considered === 0
        ? `None of the ${c.metadata.records_returned} retrieved trials names a drug, biological, dietary supplement or combination product as an intervention.`
        : "The named interventions carry no phase data.",
    filterBy: "phase",
  };

  const ongoingByPhase: ChartSpec = {
    id: "ongoing-candidates-by-phase",
    title: "Ongoing candidates by phase",
    subtitle:
      "Ongoing means the registry status is Recruiting, Enrolling by Invitation, or Active, not recruiting. A candidate is counted in a phase when at least one of its trials in that phase is ongoing.",
    unit: "ongoing candidates",
    kind: "bar",
    data: phaseSeries(c.ongoing_candidates_by_phase),
    emptyNote: `No ongoing trial in the retrieved set names a candidate product.`,
    filterBy: "phase",
  };

  const companies = c.candidates_by_company.slice(0, COMPANY_CAP);
  const byCompany: ChartSpec = {
    id: "candidates-by-company",
    title: "Candidates by company",
    subtitle:
      `${companies.length} of ${c.candidates_by_company.length} companies, largest first. A company is listed here only when a source names it: the manufacturer printed on an openFDA label, or the lead sponsor of a trial studying the product. Neither establishes that the company developed it, and ${c.candidates_with_established_developer} of ${c.distinct_candidates} candidates has a developer a retrieved source states.`,
    unit: "distinct candidates",
    kind: "bar",
    data: companies.map((b) => ({
      label: b.label,
      value: b.count,
      color: colorForSeries("company"),
    })),
    emptyNote:
      "No retrieved trial names a sponsor for a candidate product, and no openFDA label matched one.",
    filterBy: null,
  };

  return [byPhase, ongoingByPhase, byCompany].filter((chart) => chart.data.length > 0);
}

/** Interventions the registry did not type as a product, shown rather than dropped. */
export function nonDrugNote(c: CandidateAnalytics): string | null {
  if (c.non_drug_intervention_types.length === 0) return null;
  const parts = c.non_drug_intervention_types.map((b) => `${b.count} ${b.label.toLowerCase()}`);
  return `Interventions excluded from the candidate counts because the registry types them otherwise: ${parts.join("; ")}. ${c.trials_without_named_intervention} of ${c.metadata.records_returned} retrieved trials name no product candidate at all.`;
}

/**
 * Candidates per company for one phase, or for every phase when none is
 * selected. Rows come from the backend matrix, so the figure beside a company
 * is the same one its table rows support.
 */
export function companyPhaseSeries(
  c: CandidateAnalytics,
  phase: string
): ChartSpec["data"] {
  const rows = phase ? c.company_by_phase.filter((r) => r.phase === phase) : c.company_by_phase;
  const totals = new Map<string, number>();
  rows.forEach((r) => totals.set(r.company, (totals.get(r.company) ?? 0) + r.candidates));
  const color = phase ? colorForPhase(phase) : colorForSeries("company");
  return Array.from(totals.entries())
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
    .slice(0, 10)
    .map(([label, value]) => ({ label, value, color }));
}

export function companyPhaseNote(c: CandidateAnalytics, phase: string): string {
  const scope = phase ? `in ${phase}` : "across all retrieved phases";
  return `Candidate products ${scope}, counted once per company that a source names. Selecting a phase above changes this chart and the record list together. Companies here are trial sponsors or the manufacturer named on an openFDA label — a developer is stated for ${c.candidates_with_established_developer} candidate(s).`;
}
