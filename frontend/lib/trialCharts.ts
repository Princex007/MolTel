/**
 * Chart specifications derived from the backend's computed trial analytics.
 *
 * The on-screen dashboard and every export render from these same specs, so a
 * chart can never show numbers that differ from the table beside it.
 */

import type { TrialAnalytics } from "./api";
import { colorForPhase, colorForStatus, colorForSeries } from "./chartColors";

export interface ChartDatum {
  label: string;
  value: number;
  color: string;
}

export interface ChartSpec {
  id: string;
  title: string;
  /** States what is counted and, where relevant, which statuses qualify. */
  subtitle: string;
  /** "trials" | "candidates" | "companies" — shown in the chart caption. */
  unit: string;
  kind: "bar" | "timeline";
  data: ChartDatum[];
  /** Non-null when there is nothing to plot; explains why instead of leaving a blank box. */
  emptyNote: string | null;
  /** Which table filter a bar click applies. */
  filterBy?: "phase" | "status" | null;
  /** For timeline charts, the period length the backend grouped by. */
  granularity?: string | null;
}

const ONGOING_DEFINITION =
  "Ongoing means the registry status is Recruiting, Enrolling by Invitation, or Active, not recruiting.";

export function buildTrialCharts(a: TrialAnalytics): ChartSpec[] {
  const phaseCount = a.trials_by_phase.reduce((sum, b) => sum + b.count, 0);

  const chartsA: ChartSpec = {
    id: "trials-by-phase",
    title: "Distinct trials by phase",
    subtitle: `Every retrieved trial is counted once, by the phase category its registry record supports. Combined phases (for example "Phase 1 + Phase 2") stay a single category. Not Applicable and Unknown are not development stages and are coloured apart from the phases. ${phaseCount} of ${a.total_trials} records are placed in a phase bucket below; trials with no usable phase are grouped as Unknown / Not Reported rather than dropped.`,
    unit: "distinct trials",
    kind: "bar",
    data: a.trials_by_phase.map((b) => ({
      label: b.label,
      value: b.count,
      color: colorForPhase(b.label),
    })),
    emptyNote:
      a.total_trials === 0
        ? "No trials were retrieved for this query."
        : "The retrieved trials carry no phase data.",
    filterBy: "phase",
  };

  const chartsB: ChartSpec = {
    id: "ongoing-by-phase",
    title: "Ongoing trials by phase",
    subtitle: `${ONGOING_DEFINITION} Excludes not-yet-recruiting, suspended, completed, terminated and withdrawn studies.`,
    unit: "ongoing trials",
    kind: "bar",
    data: a.ongoing_trials_by_phase.map((b) => ({
      label: b.label,
      value: b.count,
      color: colorForPhase(b.label),
    })),
    emptyNote: `None of the ${a.total_trials} retrieved trials is ongoing under the definition above.`,
    filterBy: "phase",
  };

  const chartsC: ChartSpec = {
    id: "trials-by-status",
    title: "Trials by registry status",
    subtitle:
      "Status labels exactly as ClinicalTrials.gov reports them, not a MolTel grouping. Each trial carries one overall status, so these bars are mutually exclusive.",
    unit: "distinct trials",
    kind: "bar",
    data: a.trials_by_status.map((b) => ({
      label: b.label,
      value: b.count,
      color: colorForStatus(b.label),
    })),
    emptyNote: "No trials were retrieved for this query.",
    filterBy: "status",
  };

  const granularity = a.timeline_granularity === "month" ? "month" : "year";
  const excluded = a.excluded_from_timeline_count;
  const chartsD: ChartSpec = {
    id: "trial-starts-over-time",
    title: "Trial starts over time",
    subtitle: a.timeline_omitted_reason
      ? `This timeline is omitted: ${a.timeline_omitted_reason}`
      : `Registry start dates grouped by ${granularity}. Missing or unusable start dates are excluded, never estimated${
          excluded > 0 ? ` (${excluded} excluded)` : " (none excluded in this set)"
        }.`,
    unit: "trial starts",
    kind: "timeline",
    data: a.trial_starts_by_period.map((b) => ({
      label: b.period,
      value: b.count,
      color: colorForSeries("starts"),
    })),
    emptyNote: a.timeline_omitted_reason ?? "No usable start dates in these records.",
    filterBy: null,
    granularity: a.timeline_granularity,
  };

  return [chartsA, chartsB, chartsC, chartsD].filter((c) => c.data.length > 0 || c.emptyNote);
}
