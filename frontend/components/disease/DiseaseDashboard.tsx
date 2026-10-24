"use client";

import { useMemo, useState } from "react";
import type {
  ClinicalTrial,
  DiseaseAnalytics,
  DiseaseSubtype,
  EvidenceItem,
  TargetProfile,
} from "@/lib/api";
import LiteratureTable from "@/components/LiteratureTable";
import TargetTable from "@/components/TargetTable";
import ClinicalTrialTable, { EMPTY_FILTERS } from "@/components/trials/ClinicalTrialTable";

interface Props {
  analytics: DiseaseAnalytics;
  trials: ClinicalTrial[];
  papers: EvidenceItem[];
  targets: TargetProfile[];
  /** Index into `analytics.subtypes`; null means All subtypes. */
  selected: number | null;
  onSelect: (index: number | null) => void;
}

/** What the record counts on a subtype row cover. */
function Counts({ subtype }: { subtype: DiseaseSubtype }) {
  const cells: [string, number][] = [
    ["Trials", subtype.trial_nct_ids.length],
    ["Candidates", subtype.candidate_names.length],
    ["Companies", subtype.company_names.length],
    ["Papers", subtype.paper_keys.length],
    ["Targets", subtype.target_accessions.length],
  ];
  return (
    <dl className="flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-slate-600">
      {cells.map(([label, value]) => (
        <div key={label} className="flex items-baseline gap-1">
          <dt className="text-slate-400">{label}</dt>
          <dd className="font-mono font-semibold text-slate-800">{value}</dd>
        </div>
      ))}
    </dl>
  );
}

function OriginTag({ subtype }: { subtype: DiseaseSubtype }) {
  const tone =
    subtype.origin === "standardized concept"
      ? "border-indigo-200 bg-indigo-50 text-indigo-700"
      : subtype.origin === "both"
        ? "border-emerald-200 bg-emerald-50 text-emerald-700"
        : "border-slate-200 bg-slate-50 text-slate-600";
  return (
    <span className={`rounded border px-1.5 py-0.5 text-[10px] font-medium ${tone}`}>
      {subtype.origin}
    </span>
  );
}

function ChipList({ items, title, note }: { items: string[]; title: string; note?: string }) {
  return (
    <div>
      <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-wider text-slate-500">
        {title}
      </p>
      {items.length === 0 ? (
        <p className="text-[11px] text-slate-400">{note ?? "None in these records."}</p>
      ) : (
        <ul className="flex flex-wrap gap-1.5">
          {items.map((name) => (
            <li
              key={name}
              className="rounded border border-slate-200 bg-white px-2 py-0.5 text-[11px] text-slate-700"
            >
              {name}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export default function DiseaseDashboard({
  analytics,
  trials,
  papers,
  targets,
  selected,
  onSelect,
}: Props) {
  const [filters, setFilters] = useState(EMPTY_FILTERS);
  const subtype = selected === null ? null : analytics.subtypes[selected] ?? null;

  // A subtype's record lists are the ids the backend attached to it; nothing is
  // re-matched here, so the page and the export count the same records.
  const scoped = useMemo(() => {
    if (!subtype) return null;
    const ncts = new Set(subtype.trial_nct_ids);
    const keys = new Set(subtype.paper_keys);
    const names = new Set(subtype.candidate_names.map((n) => n.toLowerCase()));
    const accessions = new Set(subtype.target_accessions);
    return {
      trials: trials.filter((t) => ncts.has(t.nct_id)),
      // Mirrors the backend key: `${source}:${id or url}`.
      papers: papers.filter((p) => keys.has(`${p.source}:${p.id || p.url || ""}`)),
      targets: targets.filter((t) => accessions.has(t.accession)),
      candidates: subtype.candidate_names,
      companies: subtype.company_names,
      namedInterventions: trials
        .filter((t) => ncts.has(t.nct_id))
        .flatMap((t) => t.interventions ?? [])
        .filter((name) => !names.has(name.toLowerCase()))
        .slice(0, 20),
    };
  }, [subtype, trials, papers, targets]);

  return (
    <div className="space-y-5">
      {/* Canonical term, with the query that produced it */}
      <div className="rounded-lg border border-slate-200 bg-white px-4 py-3 shadow-sm">
        <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <p className="text-base font-semibold text-slate-900">
            {analytics.canonical_term}
          </p>
          <span className="rounded border border-indigo-200 bg-indigo-50 px-1.5 py-0.5 text-[10px] font-medium text-indigo-700">
            {analytics.concept ? "standardized concept" : "registry condition wording"}
          </span>
          {analytics.concept?.url && (
            <a
              href={analytics.concept.url}
              target="_blank"
              rel="noreferrer"
              className="text-[11px] font-medium text-indigo-600 hover:underline"
            >
              {analytics.concept.ontology} {analytics.concept.concept_id}
            </a>
          )}
        </div>
        <p className="mt-2 text-[11px] leading-relaxed text-slate-500">
          {analytics.canonical_term_provenance}
        </p>
        {analytics.synonyms.length > 0 && (
          <div className="mt-3">
            <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-wider text-slate-500">
              Other names the same concept is recorded under
            </p>
            <ul className="flex flex-wrap gap-1.5">
              {analytics.synonyms.map((s) => (
                <li
                  key={s}
                  className="rounded border border-slate-200 bg-slate-50 px-2 py-0.5 text-[11px] text-slate-600"
                >
                  {s}
                </li>
              ))}
            </ul>
          </div>
        )}
        {analytics.concept?.definition && (
          <p className="mt-3 text-[11px] leading-relaxed text-slate-500">
            <span className="font-semibold text-slate-600">Concept definition: </span>
            {analytics.concept.definition}
          </p>
        )}
      </div>

      {/* Subtype choices */}
      <div>
        <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
          <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">
            Subtypes in this query — {analytics.subtypes_with_records} with retrieved
            records, {analytics.subtypes_without_records} named by the ontology only
            {analytics.subtypes_omitted > 0 &&
              `, ${analytics.subtypes_omitted} left off for length`}
          </p>
          <button
            type="button"
            onClick={() => onSelect(null)}
            aria-pressed={selected === null}
            className={`rounded-md border px-2.5 py-1 text-[11px] font-semibold transition ${
              selected === null
                ? "border-indigo-600 bg-indigo-600 text-white"
                : "border-slate-300 bg-white text-slate-600 hover:border-indigo-300"
            }`}
          >
            All subtypes ({analytics.trials_considered} trials)
          </button>
        </div>
        <ul className="flex flex-wrap gap-1.5">
          {analytics.subtypes.map((s, index) => {
            const active = index === selected;
            const empty = s.trial_nct_ids.length === 0;
            return (
              <li key={`${s.label}-${index}`} style={{ marginLeft: s.level * 10 }}>
                <button
                  type="button"
                  onClick={() => onSelect(active ? null : index)}
                  aria-pressed={active}
                  className={`rounded-md border px-2.5 py-1 text-[11px] font-medium transition ${
                    active
                      ? "border-indigo-600 bg-indigo-600 text-white"
                      : empty
                        ? "border-dashed border-slate-300 bg-white text-slate-400 hover:border-indigo-300"
                        : "border-slate-300 bg-white text-slate-700 hover:border-indigo-300 hover:bg-indigo-50"
                  }`}
                  title={
                    s.refines
                      ? `Under ${s.refines} (${s.refines_source ?? "wording"})`
                      : s.origin
                  }
                >
                  {s.label}
                  <span className="ml-1.5 font-mono">{s.trial_nct_ids.length}</span>
                </button>
              </li>
            );
          })}
        </ul>
        <p className="mt-2 text-[11px] leading-relaxed text-slate-500">
          Indentation follows the name a subtype refines:{" "}
          <span className="font-medium">standardized hierarchy</span> is the relation the
          disease ontology itself publishes, and{" "}
          <span className="font-medium">wording containment</span> is where the nesting
          follows from the words alone. A dashed chip is a subtype these retrieved records
          do not name.
        </p>
      </div>

      {/* Selected subtype */}
      {subtype && scoped && (
        <div className="space-y-4 rounded-lg border border-indigo-200 bg-indigo-50/40 px-4 py-4">
          <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <p className="text-sm font-semibold text-slate-900">{subtype.label}</p>
            <OriginTag subtype={subtype} />
            {subtype.refines && (
              <span className="text-[11px] text-slate-500">
                under {subtype.refines} · {subtype.refines_source ?? "wording"}
              </span>
            )}
            {subtype.concept?.url && (
              <a
                href={subtype.concept.url}
                target="_blank"
                rel="noreferrer"
                className="text-[11px] font-medium text-indigo-600 hover:underline"
              >
                {subtype.concept.ontology} {subtype.concept.concept_id}
              </a>
            )}
          </div>
          {subtype.concept?.definition && (
            <p className="text-[11px] leading-relaxed text-slate-600">
              {subtype.concept.definition}
            </p>
          )}
          {subtype.availability_note && (
            <p className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-[11px] leading-relaxed text-amber-800">
              {subtype.availability_note}
            </p>
          )}
          <Counts subtype={subtype} />
          {subtype.condition_labels.length > 0 && (
            <ChipList
              title="Registry condition wording carrying this name"
              items={subtype.condition_labels}
            />
          )}

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <ChipList
              title="Candidates named by these trials"
              items={scoped.candidates}
              note="No retrieved trial naming this subtype also names an intervention."
            />
            <ChipList
              title="Sponsors and companies on these trials"
              items={scoped.companies}
              note="No sponsor is recorded on the trials attached to this subtype."
            />
          </div>
          {scoped.namedInterventions.length > 0 && (
            <p className="text-[11px] leading-relaxed text-slate-500">
              Interventions these trials name that the candidate list does not carry:{" "}
              {scoped.namedInterventions.join(", ")}.
            </p>
          )}

          <div>
            <p className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-slate-500">
              Trials attached to this subtype — {scoped.trials.length} of{" "}
              {analytics.trials_considered} retrieved for “{analytics.query}”
            </p>
            {scoped.trials.length > 0 ? (
              <ClinicalTrialTable
                trials={scoped.trials}
                filters={filters}
                onFiltersChange={setFilters}
              />
            ) : (
              <p className="text-[11px] text-slate-500">
                No trial in this retrieved set carries this wording.
              </p>
            )}
          </div>

          <div>
            <p className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-slate-500">
              Literature carrying this wording — {scoped.papers.length} of{" "}
              {analytics.papers_considered} retrieved
            </p>
            <LiteratureTable
              items={scoped.papers}
              query={analytics.query}
              scopeLabel={subtype?.label ?? null}
              targetTerms={scoped.targets
                .map((t) => t.gene ?? t.name)
                .filter((name): name is string => Boolean(name))}
            />
          </div>

          <div>
            <p className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-slate-500">
              Targets naming this wording — {scoped.targets.length} of{" "}
              {analytics.targets_considered} retrieved
            </p>
            {scoped.targets.length > 0 ? (
              <TargetTable targets={scoped.targets} />
            ) : (
              <p className="text-[11px] leading-relaxed text-slate-500">
                None of the {analytics.targets_considered} protein record(s) returned for this
                query names this subtype, so none is attached to it. A protein returned for a
                broad query is not thereby a target of the subtype — and this is not evidence
                that no such target exists, only that these retrieved records do not state one.
              </p>
            )}
          </div>
        </div>
      )}

      {!subtype && (
        <div className="rounded-lg border border-slate-200 bg-slate-50 px-4 py-3 text-[11px] leading-relaxed text-slate-600">
          <p>
            All subtypes are shown, so nothing below is filtered. {analytics.subtypes_with_records}{" "}
            subtype(s) carry retrieved records; the counts on each chip are that subtype&apos;s own
            trials, and records attached to two subtypes are counted in both, because one trial can
            name two of them.
          </p>
          {analytics.trials_without_condition_label > 0 && (
            <p className="mt-1">
              {analytics.trials_without_condition_label} retrieved trial(s) name no condition at
              all, so no subtype is claimed for them.
            </p>
          )}
          <p className="mt-1">
            Select a subtype to scope the trial, candidate, company, literature and target lists
            to the records carrying that wording.
          </p>
        </div>
      )}

      {/* Condition wording no subtype covers */}
      {analytics.unmatched_condition_labels.length > 0 && (
        <div>
          <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-wider text-slate-500">
            Other condition wording in the retrieved trials
          </p>
          <ul className="flex flex-wrap gap-1.5">
            {analytics.unmatched_condition_labels.map((bucket) => (
              <li
                key={bucket.label}
                className="rounded border border-slate-200 bg-white px-2 py-0.5 text-[11px] text-slate-600"
                title="A condition string the retrieved trials name that none of the subtypes above covers"
              >
                {bucket.label} <span className="font-mono text-slate-400">{bucket.count}</span>
              </li>
            ))}
          </ul>
          <p className="mt-1.5 text-[11px] leading-relaxed text-slate-500">
            These are broader or unrelated conditions the retrieved studies also name. They stay in
            the query totals and are not listed as subtypes of {analytics.canonical_term}.
          </p>
        </div>
      )}

      {/* How these numbers were produced */}
      <details className="rounded-lg border border-slate-200 bg-white px-4 py-3 text-[11px] text-slate-600">
        <summary className="cursor-pointer text-[10px] font-semibold uppercase tracking-wider text-slate-500">
          How subtypes and their counts were produced
        </summary>
        <p className="mt-2 leading-relaxed">{analytics.counting_rule}</p>
        <p className="mt-2 leading-relaxed">{analytics.hierarchy_note}</p>
        {analytics.limitations.length > 0 && (
          <ul className="mt-2 space-y-1 leading-relaxed">
            {analytics.limitations.map((line, i) => (
              <li key={i} className="flex gap-2">
                <span className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-slate-400" />
                <span>{line}</span>
              </li>
            ))}
          </ul>
        )}
      </details>
    </div>
  );
}
