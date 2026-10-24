"use client";

import { useMemo, useState } from "react";
import type { ClinicalTrial } from "@/lib/api";

const STATUS_STYLES: Record<string, string> = {
  Recruiting: "bg-green-50 text-green-800 border-green-300",
  "Active, not recruiting": "bg-blue-50 text-blue-700 border-blue-200",
  Completed: "bg-slate-100 text-slate-700 border-slate-300",
  Terminated: "bg-red-50 text-red-800 border-red-300",
  Withdrawn: "bg-red-50 text-red-700 border-red-200",
  Suspended: "bg-yellow-50 text-yellow-800 border-yellow-300",
  "Not yet recruiting": "bg-indigo-50 text-indigo-700 border-indigo-200",
};

const PAGE = 15;

export function StatusBadge({ status }: { status: string | null }) {
  if (!status) return <span className="text-slate-400">—</span>;
  const cls =
    STATUS_STYLES[status] ?? "bg-gray-100 text-gray-700 border-gray-300";
  return (
    <span
      className={`inline-flex items-center rounded border px-2 py-0.5 text-xs font-medium ${cls}`}
    >
      {status}
    </span>
  );
}

interface Filters {
  search: string;
  phase: string;
  status: string;
  studyType: string;
  condition: string;
}

export const EMPTY_FILTERS: Filters = {
  search: "",
  phase: "",
  status: "",
  studyType: "",
  condition: "",
};

interface Props {
  trials: ClinicalTrial[];
  filters: Filters;
  onFiltersChange: (next: Filters) => void;
}

/** Registry date "2003-01" or "2003" is shown as supplied, never invented. */
function formatDate(value: string | null): string {
  return value && /^\d{4}(-\d{2}){0,2}$/.test(value) ? value : "—";
}

// The charts bucket studies by phase_category, so the table filters on the same
// key. Otherwise clicking a "Phase 2 + Phase 3" bar would find nothing.
export const UNKNOWN_PHASE = "Unknown / Not Reported";

export function phaseOf(trial: ClinicalTrial): string {
  return trial.phase_category ?? trial.phase ?? UNKNOWN_PHASE;
}

function Option({ value, label }: { value: string; label: string }) {
  return <option value={value}>{label}</option>;
}

export default function ClinicalTrialTable({
  trials,
  filters,
  onFiltersChange,
}: Props) {
  const [visible, setVisible] = useState(PAGE);

  const set = (patch: Partial<Filters>) => {
    onFiltersChange({ ...filters, ...patch });
    setVisible(PAGE);
  };

  const { phaseOptions, statusOptions, studyTypeOptions, conditionOptions } =
    useMemo(() => {
      const phases = new Set<string>();
      const statuses = new Set<string>();
      const types = new Set<string>();
      const conditions = new Set<string>();
      trials.forEach((t) => {
        phases.add(phaseOf(t));
        if (t.status) statuses.add(t.status);
        if (t.study_type) types.add(t.study_type);
        t.conditions.forEach((c) => conditions.add(c));
      });
      const sorted = (s: Set<string>) => Array.from(s).sort();
      return {
        phaseOptions: sorted(phases),
        statusOptions: sorted(statuses),
        studyTypeOptions: sorted(types),
        conditionOptions: sorted(conditions).slice(0, 60),
      };
    }, [trials]);

  const filtered = useMemo(() => {
    const needle = filters.search.trim().toLowerCase();
    return trials.filter((t) => {
      if (filters.phase && phaseOf(t) !== filters.phase) return false;
      if (filters.status && (t.status ?? "") !== filters.status) return false;
      if (filters.studyType && (t.study_type ?? "") !== filters.studyType)
        return false;
      if (
        filters.condition &&
        !t.conditions.some((c) => c.toLowerCase() === filters.condition.toLowerCase())
      )
        return false;
      if (needle) {
        const haystack = [
          t.title,
          t.nct_id,
          t.sponsor,
          t.brief_summary,
          ...t.conditions,
          ...t.interventions,
        ]
          .filter(Boolean)
          .join(" ")
          .toLowerCase();
        if (!haystack.includes(needle)) return false;
      }
      return true;
    });
  }, [trials, filters]);

  const anyFilter =
    filters.search ||
    filters.phase ||
    filters.status ||
    filters.studyType ||
    filters.condition;

  const selectCls =
    "w-full rounded-md border border-slate-300 bg-white px-2.5 py-1.5 text-xs text-slate-700 focus:border-indigo-500 focus:outline-none";

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-5">
        <label className="block">
          <span className="mb-1 block text-[11px] font-semibold uppercase tracking-wider text-slate-500">
            Search
          </span>
          <input
            type="search"
            value={filters.search}
            onChange={(e) => set({ search: e.target.value })}
            placeholder="Title, NCT, sponsor, intervention"
            className={selectCls}
          />
        </label>
        <label className="block">
          <span className="mb-1 block text-[11px] font-semibold uppercase tracking-wider text-slate-500">
            Phase
          </span>
          <select
            value={filters.phase}
            onChange={(e) => set({ phase: e.target.value })}
            className={selectCls}
          >
            <Option value="" label="All phases" />
            {phaseOptions.map((v) => (
              <Option key={v} value={v} label={v} />
            ))}
          </select>
        </label>
        <label className="block">
          <span className="mb-1 block text-[11px] font-semibold uppercase tracking-wider text-slate-500">
            Recruitment status
          </span>
          <select
            value={filters.status}
            onChange={(e) => set({ status: e.target.value })}
            className={selectCls}
          >
            <Option value="" label="All statuses" />
            {statusOptions.map((v) => (
              <Option key={v} value={v} label={v} />
            ))}
          </select>
        </label>
        <label className="block">
          <span className="mb-1 block text-[11px] font-semibold uppercase tracking-wider text-slate-500">
            Study type
          </span>
          <select
            value={filters.studyType}
            onChange={(e) => set({ studyType: e.target.value })}
            className={selectCls}
          >
            <Option value="" label="All types" />
            {studyTypeOptions.map((v) => (
              <Option key={v} value={v} label={v} />
            ))}
          </select>
        </label>
        <label className="block">
          <span className="mb-1 block text-[11px] font-semibold uppercase tracking-wider text-slate-500">
            Condition
          </span>
          <select
            value={filters.condition}
            onChange={(e) => set({ condition: e.target.value })}
            className={selectCls}
          >
            <Option value="" label="All conditions" />
            {conditionOptions.map((v) => (
              <Option key={v} value={v} label={v.length > 40 ? `${v.slice(0, 40)}…` : v} />
            ))}
          </select>
        </label>
      </div>

      <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
        <span>
          Showing {Math.min(visible, filtered.length)} of {filtered.length}
          {anyFilter ? ` filtered from ${trials.length}` : ""} retrieved
          trial{trials.length === 1 ? "" : "s"}.
        </span>
        {anyFilter && (
          <button
            type="button"
            onClick={() => set(EMPTY_FILTERS)}
            className="rounded border border-slate-300 px-2 py-0.5 font-medium text-slate-600 hover:bg-slate-50"
          >
            Clear filters
          </button>
        )}
      </div>

      {filtered.length === 0 ? (
        <p className="rounded-md border border-dashed border-slate-300 py-8 text-center text-sm text-slate-400">
          No retrieved trial matches these filters. Clear them to see the full
          result set.
        </p>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-slate-200">
          <table className="min-w-full divide-y divide-slate-200 bg-white text-sm">
            <thead className="bg-slate-50">
              <tr>
                {["NCT ID", "Title", "Status", "Phase", "Condition", "Intervention", "Start", "Completion", "Enrollment"].map(
                  (heading) => (
                    <th
                      key={heading}
                      scope="col"
                      className={`px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-slate-500 ${
                        ["Condition", "Intervention", "Start", "Completion", "Enrollment"].includes(
                          heading
                        )
                          ? "hidden lg:table-cell"
                          : ""
                      }`}
                    >
                      {heading}
                    </th>
                  )
                )}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {filtered.slice(0, visible).map((trial) => (
                <tr key={trial.nct_id} className="transition-colors hover:bg-slate-50">
                  <td className="whitespace-nowrap px-4 py-3">
                    <a
                      href={trial.url ?? `https://clinicaltrials.gov/study/${trial.nct_id}`}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="font-mono text-xs text-indigo-700 hover:underline"
                    >
                      {trial.nct_id}
                    </a>
                  </td>
                  <td className="max-w-sm px-4 py-3">
                    <span className="line-clamp-2 text-slate-800">
                      {trial.title ?? "—"}
                    </span>
                    <details className="mt-1">
                      <summary className="cursor-pointer text-[11px] text-indigo-600">
                        Details
                      </summary>
                      <div className="mt-1 space-y-1 text-[11px] text-slate-500">
                        <p>{trial.brief_summary ?? "No brief summary supplied."}</p>
                        <p>
                          Sponsor: {trial.sponsor ?? "—"} · Original status:{" "}
                          {trial.overall_status ?? "—"} · Original phases:{" "}
                          {trial.phases.join(", ") || "—"}
                          {trial.last_update_date
                            ? ` · Last updated ${trial.last_update_date}`
                            : ""}
                        </p>
                      </div>
                    </details>
                  </td>
                  <td className="px-4 py-3">
                    <StatusBadge status={trial.status} />
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 text-slate-600">
                    {trial.phase ?? (
                      <span className="text-slate-400">Not reported</span>
                    )}
                  </td>
                  <td className="hidden px-4 py-3 text-xs text-slate-500 lg:table-cell">
                    {trial.conditions.slice(0, 2).join(", ") || "—"}
                  </td>
                  <td className="hidden px-4 py-3 text-xs text-slate-500 lg:table-cell">
                    {trial.interventions.slice(0, 2).join(", ") || "—"}
                  </td>
                  <td className="hidden whitespace-nowrap px-4 py-3 text-xs text-slate-500 lg:table-cell">
                    {formatDate(trial.start_date)}
                  </td>
                  <td className="hidden whitespace-nowrap px-4 py-3 text-xs text-slate-500 lg:table-cell">
                    <div>Primary: {formatDate(trial.primary_completion_date)}</div>
                    <div>Study: {formatDate(trial.completion_date)}</div>
                  </td>
                  <td className="hidden whitespace-nowrap px-4 py-3 text-xs text-slate-500 lg:table-cell">
                    {trial.enrollment_count !== null
                      ? `${trial.enrollment_count.toLocaleString()}${
                          trial.enrollment_type ? ` (${trial.enrollment_type})` : ""
                        }`
                      : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {visible < filtered.length && (
        <div className="flex justify-center">
          <button
            type="button"
            onClick={() => setVisible((v) => v + PAGE)}
            className="rounded-md border border-slate-300 px-4 py-2 text-xs font-semibold text-slate-600 hover:bg-slate-50"
          >
            Show {Math.min(PAGE, filtered.length - visible)} more
          </button>
        </div>
      )}
    </div>
  );
}

export type { Filters as TrialFilters };
