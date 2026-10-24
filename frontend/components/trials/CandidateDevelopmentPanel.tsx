"use client";

import { useMemo, useState } from "react";
import type { CandidateAnalytics } from "@/lib/api";
import { buildCandidateCharts, companyPhaseNote, companyPhaseSeries, nonDrugNote } from "@/lib/candidateCharts";
import { colorForPhase } from "@/lib/chartColors";
import BarBreakdown from "@/components/charts/BarBreakdown";
import CandidateTable from "./CandidateTable";

interface Props {
  candidates: CandidateAnalytics | null;
  /** Distinct trials, so the candidate figure is never read as a trial figure. */
  totalTrials: number;
}

function Figure({ label, value, hint }: { label: string; value: string; hint: string }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-3 shadow-sm">
      <p className="text-xl font-semibold leading-none text-slate-900">{value}</p>
      <p className="mt-1.5 text-xs font-medium text-slate-700">{label}</p>
      <p className="mt-0.5 text-[10px] leading-relaxed text-slate-400">{hint}</p>
    </div>
  );
}

export default function CandidateDevelopmentPanel({ candidates, totalTrials }: Props) {
  const [phaseFilter, setPhaseFilter] = useState("");

  const charts = useMemo(
    () => (candidates ? buildCandidateCharts(candidates) : []),
    [candidates]
  );

  const companySeries = useMemo(
    () => (candidates ? companyPhaseSeries(candidates, phaseFilter) : []),
    [candidates, phaseFilter]
  );

  if (!candidates) return null;

  const note = nonDrugNote(candidates);
  const selectPhase = (label: string) => {
    setPhaseFilter((current) => (current === label ? "" : label));
    document
      .getElementById("candidate-records")
      ?.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  if (candidates.distinct_candidates === 0) {
    return (
      <div className="rounded-lg border border-slate-200 bg-slate-50 px-4 py-3 text-[11px] leading-relaxed text-slate-600">
        <p className="text-sm font-semibold text-slate-800">No candidate products in this set</p>
        <p className="mt-1">
          {candidates.candidate_trials_considered} of {candidates.metadata.records_returned}{" "}
          retrieved trials name a drug, biological, dietary supplement or combination product as an
          intervention, so no candidate-level counts are shown.
        </p>
        {note && <p className="mt-1">{note}</p>}
      </div>
    );
  }

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-4">
        <Figure
          label="Distinct candidates"
          value={String(candidates.distinct_candidates)}
          hint={`Products named as interventions in ${candidates.candidate_trials_considered} of ${totalTrials} distinct trials, including ${candidates.comparator_candidates} placebo or sham comparator name(s) that the registry types as a drug intervention. Candidates are never the same number as trials.`}
        />
        <Figure
          label="Trials naming a candidate"
          value={String(candidates.candidate_trials_considered)}
          hint={`${candidates.trials_without_named_intervention} retrieved trial(s) name no candidate product and are excluded from every figure here.`}
        />
        <Figure
          label="Companies on a source record"
          value={String(candidates.candidates_by_company.length)}
          hint={`Only companies a retrieved source names: ${candidates.candidates_with_openfda_label} candidate(s) match an openFDA label, the rest come from registry sponsorship.`}
        />
        <Figure
          label="Developer established"
          value={String(candidates.candidates_with_established_developer)}
          hint={
            candidates.candidates_with_established_developer === 0
              ? "Sponsorship and label manufacture are not development. No retrieved source states a developer for any candidate here."
              : "Sponsorship and label manufacture are not development; this counts only candidates a retrieved source states a developer for."
          }
        />
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {charts.map((chart) => (
          <div
            key={chart.id}
            className="flex flex-col rounded-lg border border-slate-200 bg-white p-4 shadow-sm"
          >
            <h4 className="text-sm font-semibold text-slate-800">{chart.title}</h4>
            <p className="mt-1 mb-3 text-[11px] leading-relaxed text-slate-500">{chart.subtitle}</p>
            <div className="mt-auto">
              {chart.data.length === 0 ? (
                <p className="py-8 text-center text-sm text-slate-400">
                  {chart.emptyNote ?? "Nothing to plot for these records."}
                </p>
              ) : (
                <BarBreakdown
                  data={chart.data.map((d) => ({ label: d.label, count: d.value, color: d.color }))}
                  rotated
                  unit={chart.unit}
                  activeLabel={chart.filterBy === "phase" ? phaseFilter || null : null}
                  onBarClick={chart.filterBy === "phase" ? selectPhase : undefined}
                  ariaLabel={chart.title}
                  height={Math.max(180, 34 * chart.data.length + 60)}
                />
              )}
            </div>
            <p className="mt-2 text-[10px] uppercase tracking-wider text-slate-400">
              Counts {chart.unit}
            </p>
          </div>
        ))}
      </div>

      <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
        <h4 className="text-sm font-semibold text-slate-800">Candidate development pipeline</h4>
        <p className="mt-1 text-[11px] leading-relaxed text-slate-500">
          Select a phase to list the candidates with at least one retrieved trial in it. A product
          can appear in several phases; Not Applicable and Unknown are not development stages and
          are shown apart.
        </p>
        <div className="mt-3 flex flex-wrap gap-2">
          {candidates.candidates_by_phase.map((bucket) => (
            <button
              key={bucket.label}
              type="button"
              onClick={() => selectPhase(bucket.label)}
              aria-pressed={phaseFilter === bucket.label}
              className={`rounded-full border px-3 py-1 text-xs ${
                phaseFilter === bucket.label
                  ? "border-slate-800 bg-slate-800 text-white"
                  : "border-slate-300 bg-white text-slate-700 hover:bg-slate-50"
              }`}
              style={{ boxShadow: `inset 3px 0 0 0 ${colorForPhase(bucket.label)}` }}
            >
              {bucket.label} · {bucket.count}
            </button>
          ))}
          {phaseFilter && (
            <button
              type="button"
              onClick={() => setPhaseFilter("")}
              className="rounded-full border border-dashed border-slate-300 px-3 py-1 text-xs text-slate-600 hover:bg-slate-50"
            >
              Clear phase
            </button>
          )}
        </div>

        <div className="mt-4 border-t border-slate-100 pt-3">
          <h5 className="text-xs font-semibold uppercase tracking-wider text-slate-600">
            Candidates by company {phaseFilter ? `— ${phaseFilter}` : "— all phases"}
          </h5>
          <p className="mt-1 text-[11px] leading-relaxed text-slate-500">
            {companyPhaseNote(candidates, phaseFilter)}
          </p>
          {companySeries.length === 0 ? (
            <p className="py-6 text-center text-sm text-slate-400">
              No source-named company is attached to a candidate{" "}
              {phaseFilter ? `in ${phaseFilter}` : "in these records"}.
            </p>
          ) : (
            <BarBreakdown
              data={companySeries.map((d) => ({ label: d.label, count: d.value, color: d.color }))}
              rotated
              unit="candidates"
              ariaLabel={`Candidates by company ${phaseFilter || "across all phases"}`}
              height={Math.max(170, 34 * companySeries.length + 50)}
            />
          )}
        </div>
      </div>

      {note && (
        <p className="rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-[11px] leading-relaxed text-slate-600">
          {note}
        </p>
      )}

      <div id="candidate-records" className="scroll-mt-6">
        <h4 className="mb-1 text-sm font-semibold uppercase tracking-widest text-slate-500">
          Candidate records
        </h4>
        <p className="mb-3 text-[11px] text-slate-500">
          One row per product name the registry lists as an intervention. Expand a row for the
          trials, indications and dates behind it.
        </p>
        <CandidateTable
          candidates={candidates.records}
          phaseFilter={phaseFilter}
          onPhaseFilterChange={setPhaseFilter}
        />
      </div>
    </div>
  );
}
