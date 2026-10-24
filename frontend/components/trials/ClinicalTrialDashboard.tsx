"use client";

import { useMemo, useState } from "react";
import type { CandidateAnalytics, ClinicalTrial, TrialAnalytics, TrialRetrievalMetadata } from "@/lib/api";
import { buildTrialCharts, type ChartSpec } from "@/lib/trialCharts";
import BarBreakdown from "@/components/charts/BarBreakdown";
import StartTimeline from "@/components/charts/StartTimeline";
import CandidateDevelopmentPanel from "./CandidateDevelopmentPanel";
import ClinicalTrialTable, {
  EMPTY_FILTERS,
  type TrialFilters,
} from "./ClinicalTrialTable";

interface Props {
  trials: ClinicalTrial[];
  analytics: TrialAnalytics | null;
  candidateAnalytics: CandidateAnalytics | null;
  metadata: TrialRetrievalMetadata | null;
}

function ChartCard({
  chart,
  children,
}: {
  chart: ChartSpec;
  children: React.ReactNode;
}) {
  return (
    <div className="flex flex-col rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
      <h3 className="text-sm font-semibold text-slate-800">{chart.title}</h3>
      <p className="mt-1 mb-3 text-[11px] leading-relaxed text-slate-500">
        {chart.subtitle}
      </p>
      <div className="mt-auto">{children}</div>
      <p className="mt-2 text-[10px] uppercase tracking-wider text-slate-400">
        Counts {chart.unit}
      </p>
    </div>
  );
}

function MetricCard({
  label,
  value,
  hint,
}: {
  label: string;
  value: number;
  hint: string;
}) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-3 shadow-sm">
      <p className="text-xl font-semibold leading-none text-slate-900">{value}</p>
      <p className="mt-1.5 text-xs font-medium text-slate-700">{label}</p>
      <p className="mt-0.5 text-[10px] leading-relaxed text-slate-400">{hint}</p>
    </div>
  );
}

function ChartBody({
  chart,
  activeLabel,
  onBarClick,
}: {
  chart: ChartSpec;
  activeLabel: string | null;
  onBarClick: ((label: string) => void) | undefined;
}) {
  if (chart.data.length === 0) {
    return (
      <p className="py-8 text-center text-sm text-slate-400">
        {chart.emptyNote ?? "Nothing to plot for these records."}
      </p>
    );
  }
  if (chart.kind === "timeline") {
    return (
      <StartTimeline
        data={chart.data.map((d) => ({ period: d.label, count: d.value }))}
        granularity={chart.granularity ?? null}
      />
    );
  }
  return (
    <BarBreakdown
      data={chart.data.map((d) => ({ label: d.label, count: d.value, color: d.color }))}
      rotated
      unit={chart.unit}
      activeLabel={activeLabel}
      onBarClick={onBarClick}
      ariaLabel={chart.title}
      height={Math.max(180, 34 * chart.data.length + 60)}
    />
  );
}

export default function ClinicalTrialDashboard({
  trials,
  analytics,
  candidateAnalytics,
  metadata,
}: Props) {
  const [filters, setFilters] = useState<TrialFilters>(EMPTY_FILTERS);

  const charts = useMemo(() => (analytics ? buildTrialCharts(analytics) : []), [analytics]);

  // MolTel's derived grouping of the registry's own status labels. Each record
  // lands in exactly one category, so the column reconciles with the total.
  const grouping = useMemo(() => {
    const byCategory = new Map<string, { label: string; count: number; statuses: Set<string> }>();
    for (const t of trials) {
      const key = t.status_category ?? "other_or_unclear";
      const label = t.status_category_label ?? "Other or unclear";
      const entry = byCategory.get(key) ?? { label, count: 0, statuses: new Set<string>() };
      entry.count += 1;
      if (t.overall_status) entry.statuses.add(t.overall_status);
      byCategory.set(key, entry);
    }
    return Array.from(byCategory.values()).sort((a, b) => b.count - a.count);
  }, [trials]);

  // The registry could not be consulted. Zero-filled charts here would read as
  // "no trials exist", which is a different claim from "we could not ask".
  if (!analytics) {
    return (
      <div className="rounded-lg border border-red-200 bg-red-50 px-5 py-6">
        <p className="text-sm font-semibold text-red-800">No trial data available</p>
        <p className="mt-1 text-xs text-red-700">
          {metadata?.note ??
            "ClinicalTrials.gov could not be consulted for this query."}{" "}
          The rest of this dossier is unaffected, and no trial counts are shown
          because none were retrieved.
        </p>
      </div>
    );
  }

  const retrieved = analytics.metadata.retrieved_at
    ? new Date(analytics.metadata.retrieved_at).toLocaleString()
    : "unknown time";

  const filterToPhase = (label: string) => {
    setFilters({ ...EMPTY_FILTERS, phase: label });
    document
      .getElementById("trial-records")
      ?.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  const filterToStatus = (label: string) => {
    setFilters({ ...EMPTY_FILTERS, status: label });
    document
      .getElementById("trial-records")
      ?.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  const clickFor = (chart: ChartSpec) =>
    chart.filterBy === "phase"
      ? filterToPhase
      : chart.filterBy === "status"
        ? filterToStatus
        : undefined;

  const activeFor = (chart: ChartSpec) =>
    chart.filterBy === "phase"
      ? filters.phase || null
      : chart.filterBy === "status"
        ? filters.status || null
        : null;

  const groupingTotal = grouping.reduce((s, g) => s + g.count, 0);

  return (
    <div className="space-y-5">
      <div className="rounded-lg border border-slate-200 bg-slate-50 px-4 py-3 text-[11px] leading-relaxed text-slate-600">
        <p>
          <span className="font-semibold uppercase tracking-wider text-slate-500">
            Search scope
          </span>{" "}
          — query{" "}
          <code className="font-mono">“{analytics.metadata.query}”</code> against{" "}
          {analytics.metadata.source}, retrieved {retrieved}.{" "}
          {analytics.metadata.records_returned} distinct record
          {analytics.metadata.records_returned === 1 ? "" : "s"} analysed.{" "}
          {analytics.metadata.has_more
            ? "The registry reported further matching records beyond those retrieved."
            : "These are the retrieved records, not every trial in the registry."}
        </p>
        {analytics.metadata.note && <p className="mt-1">{analytics.metadata.note}</p>}
      </div>

      {/* The three figures no chart already carries. */}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <MetricCard
          label="Distinct trials retrieved"
          value={analytics.total_trials}
          hint="Deduplicated by NCT ID. Every status, phase and table row below describes these records."
        />
        <MetricCard
          label="Ongoing"
          value={analytics.ongoing_trials}
          hint={`Recruiting (${analytics.recruiting_trials}) + Active, not recruiting (${analytics.active_not_recruiting_trials}). A re-cut of the same records — never added to the status totals.`}
        />
        <MetricCard
          label="Phase not reported"
          value={analytics.trials_with_unreported_phase}
          hint="A phase gap, not a status. These trials are already inside the counts above and appear as Unknown / Not Reported in the phase chart."
        />
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {charts.map((chart) => (
          <ChartCard key={chart.id} chart={chart}>
            <ChartBody
              chart={chart}
              activeLabel={activeFor(chart)}
              onBarClick={clickFor(chart)}
            />
            {chart.id === "trials-by-status" && (
              <div className="mt-3 border-t border-slate-100 pt-3">
                <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-wider text-slate-500">
                  Same records, grouped by MolTel
                </p>
                <table className="w-full text-[11px]">
                  <thead>
                    <tr className="text-left text-slate-500">
                      <th className="py-1 font-medium">Derived category</th>
                      <th className="py-1 font-medium">Registry statuses inside it</th>
                      <th className="py-1 text-right font-medium">Trials</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {grouping.map((g) => (
                      <tr key={g.label}>
                        <td className="py-1 pr-2 text-slate-700">{g.label}</td>
                        <td className="py-1 pr-2 text-slate-500">
                          {Array.from(g.statuses).join(", ") || "—"}
                        </td>
                        <td className="py-1 text-right font-mono text-slate-800">
                          {g.count}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <p className="mt-1.5 text-[10px] leading-relaxed text-slate-500">
                  These {grouping.length} categories are mutually exclusive and
                  total{" "}
                  <span className="font-mono">{groupingTotal}</span> of{" "}
                  {analytics.total_trials} records — no status is dropped,
                  unrecognised ones land in Other or unclear. Registry status is
                  not an outcome: completed does not mean successful, and
                  recruiting does not mean effective.
                </p>
              </div>
            )}
          </ChartCard>
        ))}
      </div>

      <div className="scroll-mt-6">
        <h3 className="mb-1 text-sm font-semibold uppercase tracking-widest text-slate-500">
          Candidate-Level Development
        </h3>
        <p className="mb-3 text-[11px] leading-relaxed text-slate-500">
          The products the retrieved trials name as interventions, counted separately from the
          studies themselves. A candidate is not a trial, and a sponsor or label
          manufacturer is not stated as a developer unless a retrieved source says so.
        </p>
        <CandidateDevelopmentPanel
          candidates={candidateAnalytics}
          totalTrials={analytics.total_trials}
        />
      </div>

      <div id="trial-records" className="scroll-mt-6">
        <h3 className="mb-1 text-sm font-semibold uppercase tracking-widest text-slate-500">
          Retrieved Trial Records
        </h3>
        <p className="mb-3 text-[11px] text-slate-500">
          The authoritative record list for every count and chart above. Click a
          phase or status bar to filter it.
        </p>
        <ClinicalTrialTable
          trials={trials}
          filters={filters}
          onFiltersChange={setFilters}
        />
      </div>
    </div>
  );
}
