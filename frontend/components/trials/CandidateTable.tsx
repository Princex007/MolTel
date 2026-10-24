"use client";

import { useMemo, useState } from "react";
import type { CandidateRecord } from "@/lib/api";

const PAGE = 12;

/** Registry dates arrive as "2003", "2003-01" or "2003-01-15"; shown exactly so. */
function dateOr(value: string | null, fallback = "Not reported by the registry"): string {
  return value && /^\d{4}(-\d{2}){0,2}$/.test(value) ? value : fallback;
}

function listOr(values: string[], fallback: string): string {
  return values.length > 0 ? values.join("; ") : fallback;
}

/** A row that lists every sponsor is unreadable; the expansion carries the rest. */
function capList(values: string[], max: number, fallback: string): string {
  if (values.length === 0) return fallback;
  if (values.length <= max) return values.join(", ");
  return `${values.slice(0, max).join(", ")} +${values.length - max} more`;
}

type SortKey = "trials" | "name" | "phase" | "update";

interface Props {
  candidates: CandidateRecord[];
  /** Phase label a chart bar selected, or "" for no filter. */
  phaseFilter: string;
  onPhaseFilterChange: (phase: string) => void;
}

const COLUMNS: { key: SortKey | null; label: string; align?: string }[] = [
  { key: "name", label: "Candidate" },
  { key: "phase", label: "Phase(s)" },
  { key: null, label: "Registry status" },
  { key: "trials", label: "Trials", align: "text-right" },
  { key: null, label: "Trial sponsor" },
  { key: null, label: "Company on a source record" },
  { key: null, label: "Developer" },
  { key: "update", label: "Last registry update" },
  { key: null, label: "Sources" },
];

export default function CandidateTable({
  candidates,
  phaseFilter,
  onPhaseFilterChange,
}: Props) {
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState<SortKey>("trials");
  const [descending, setDescending] = useState(true);
  const [visible, setVisible] = useState(PAGE);
  const [expanded, setExpanded] = useState<string | null>(null);

  const phaseOptions = useMemo(() => {
    const set = new Set<string>();
    candidates.forEach((c) => c.phases.forEach((p) => set.add(p.phase)));
    return Array.from(set).sort();
  }, [candidates]);

  const filtered = useMemo(() => {
    const needle = search.trim().toLowerCase();
    const rows = candidates.filter((c) => {
      if (phaseFilter && !c.phases.some((p) => p.phase === phaseFilter)) return false;
      if (!needle) return true;
      return [
        c.name,
        ...c.matched_names,
        ...c.conditions,
        ...c.sponsors,
        c.label_manufacturer ?? "",
        c.fda_application_number ?? "",
        ...c.nct_ids,
      ]
        .join(" ")
        .toLowerCase()
        .includes(needle);
    });
    const value = (c: CandidateRecord): string | number => {
      switch (sort) {
        case "name":
          return c.name.toLowerCase();
        case "phase":
          return c.highest_phase ?? "zzz";
        case "update":
          return c.last_update_date ?? "";
        default:
          return c.trials;
      }
    };
    const dir = descending ? -1 : 1;
    return [...rows].sort((a, b) => {
      const av = value(a);
      const bv = value(b);
      if (typeof av === "number" && typeof bv === "number") return dir * (av - bv);
      return dir * String(av).localeCompare(String(bv));
    });
  }, [candidates, search, phaseFilter, sort, descending]);

  const shown = filtered.slice(0, visible);

  const sortBy = (key: SortKey) => {
    if (key === sort) setDescending(!descending);
    else {
      setSort(key);
      setDescending(true);
    }
    setVisible(PAGE);
  };

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <label className="flex-1 min-w-[220px]">
          <span className="sr-only">Search candidates</span>
          <input
            type="search"
            value={search}
            onChange={(e) => {
              setSearch(e.target.value);
              setVisible(PAGE);
            }}
            placeholder="Search candidate, indication, sponsor or NCT ID"
            className="w-full rounded-md border border-slate-300 px-3 py-1.5 text-sm"
          />
        </label>
        <label className="text-xs text-slate-600">
          <span className="sr-only">Filter by phase</span>
          <select
            value={phaseFilter}
            onChange={(e) => {
              onPhaseFilterChange(e.target.value);
              setVisible(PAGE);
            }}
            className="rounded-md border border-slate-300 px-2 py-1.5 text-sm"
          >
            <option value="">All phases</option>
            {phaseOptions.map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </select>
        </label>
        <p className="text-[11px] text-slate-500">
          {filtered.length} of {candidates.length} candidates
        </p>
      </div>

      <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white">
        <table className="w-full text-left text-[11px]">
          <thead className="bg-slate-50 text-slate-600">
            <tr>
              {COLUMNS.map((col) => (
                <th key={col.label} className={`px-2 py-1.5 font-semibold ${col.align ?? ""}`}>
                  {col.key ? (
                    <button
                      type="button"
                      onClick={() => sortBy(col.key as SortKey)}
                      className="underline decoration-slate-300 underline-offset-2 hover:text-slate-900"
                    >
                      {col.label}
                      {sort === col.key ? (descending ? " ▾" : " ▴") : ""}
                    </button>
                  ) : (
                    col.label
                  )}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100 align-top">
            {shown.map((c) => (
              <CandidateRow
                key={c.name}
                record={c}
                expanded={expanded === c.name}
                onToggle={() => setExpanded(expanded === c.name ? null : c.name)}
              />
            ))}
            {shown.length === 0 && (
              <tr>
                <td colSpan={COLUMNS.length} className="px-3 py-6 text-center text-slate-400">
                  No candidate matches this filter.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {visible < filtered.length && (
        <button
          type="button"
          onClick={() => setVisible((v) => v + PAGE)}
          className="rounded-md border border-slate-300 px-3 py-1.5 text-xs text-slate-700 hover:bg-slate-50"
        >
          Show {Math.min(PAGE, filtered.length - visible)} more of {filtered.length} candidates
        </button>
      )}
    </div>
  );
}

function CandidateRow({
  record,
  expanded,
  onToggle,
}: {
  record: CandidateRecord;
  expanded: boolean;
  onToggle: () => void;
}) {
  return (
    <>
      <tr>
        <td className="px-2 py-1.5">
          <button
            type="button"
            onClick={onToggle}
            className="text-left font-semibold text-slate-800 underline decoration-slate-200 underline-offset-2 hover:decoration-slate-400"
          >
            {record.name}
          </button>
          <p className="text-[10px] text-slate-500">
            {record.intervention_types.join(", ") || "type not reported"}
          </p>
        </td>
        <td className="px-2 py-1.5 text-slate-700">
          {capList(record.phases.map((p) => p.phase), 3, "—")}
        </td>
        <td className="px-2 py-1.5 text-slate-700">
          {capList(
            record.statuses.map((s) => `${s.label} (${s.count})`),
            3,
            "—"
          )}
        </td>
        <td className="px-2 py-1.5 text-right font-mono text-slate-800">{record.trials}</td>
        <td className="px-2 py-1.5 text-slate-700">
          {capList(record.sponsors, 2, "No sponsor recorded")}
        </td>
        <td className="px-2 py-1.5 text-slate-700">
          {record.label_manufacturer
            ? `${record.label_manufacturer} (manufacturer on an openFDA label)`
            : record.fda_application_number
              ? `${record.fda_application_number} (openFDA application number)`
              : "No matched openFDA label"}
        </td>
        <td className="px-2 py-1.5 text-slate-500 italic">{record.developer_note}</td>
        <td className="px-2 py-1.5 text-slate-700">{dateOr(record.last_update_date)}</td>
        <td className="px-2 py-1.5">
          {record.source_links.length > 0 ? (
            <a
              href={record.source_links[0]}
              target="_blank"
              rel="noreferrer"
              className="text-blue-700 underline"
            >
              registry
            </a>
          ) : (
            <span className="text-slate-400">—</span>
          )}
          {record.label_source_url && (
            <>
              {" · "}
              <a
                href={record.label_source_url}
                target="_blank"
                rel="noreferrer"
                className="text-blue-700 underline"
              >
                label
              </a>
            </>
          )}
        </td>
      </tr>
      {expanded && (
        <tr className="bg-slate-50/70">
          <td colSpan={COLUMNS.length} className="px-3 py-2 text-[11px] leading-relaxed text-slate-700">
            <p>
              <span className="font-semibold">Spellings in the registry: </span>
              {record.matched_names.join("; ")}
            </p>
            <p>
              <span className="font-semibold">Phases as registered: </span>
              {listOr(
                record.phases.map((p) => `${p.phase} (${p.trials} trial(s))`),
                "No phase reported on these trials"
              )}
            </p>
            <p>
              <span className="font-semibold">Registry statuses: </span>
              {listOr(
                record.statuses.map((s) => `${s.label} (${s.count})`),
                "No status reported"
              )}
            </p>
            <p>
              <span className="font-semibold">Trial sponsors: </span>
              {listOr(record.sponsors, "No sponsor recorded on these trials")}
            </p>
            <p>
              <span className="font-semibold">Indications: </span>
              {listOr(record.conditions, "No condition text on the trials naming this product")}
            </p>
            <p>
              <span className="font-semibold">Collaborators named by the registry: </span>
              {listOr(record.collaborators, "None")}{" "}
              <span className="text-slate-500">
                (partners of the sponsor; the registry does not describe them as developers)
              </span>
            </p>
            <p>
              <span className="font-semibold">Trials: </span>
              {record.nct_ids.join(", ")}
            </p>
            {record.label_note && (
              <p>
                <span className="font-semibold">Matched openFDA label: </span>
                {record.fda_application_number ?? "no application number on the record"}
                {" · "}
                {record.label_manufacturer ?? "no manufacturer named on the record"} —{" "}
                {record.label_note}
              </p>
            )}
            <p>
              <span className="font-semibold">Earliest start: </span>
              {dateOr(record.start_date)} · <span className="font-semibold">Latest completion: </span>
              {dateOr(record.completion_date)} ·{" "}
              <span className="font-semibold">Ongoing trials: </span>
              {record.ongoing_trials}
            </p>
            <p>
              <span className="font-semibold">MolTel retrieval time: </span>
              {record.retrieved_at ? new Date(record.retrieved_at).toLocaleString() : "unknown"}
            </p>
            <p className="mt-1 text-[10px] text-slate-500">
              Names are matched only on case and spacing, so salts, esters and formulations stay
              separate candidates. Nothing here infers a developer from a sponsor.
            </p>
          </td>
        </tr>
      )}
    </>
  );
}
