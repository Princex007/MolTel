"use client";

import { useState } from "react";
import type { EvidenceStrength } from "@/lib/api";
import BarBreakdown from "@/components/charts/BarBreakdown";

const UNCLASSIFIED_KEY = "unclassified";

export default function EvidenceStrengthPanel({
  strength,
}: {
  strength: EvidenceStrength;
}) {
  const [open, setOpen] = useState<string | null>(null);

  if (strength.categories.length === 0) {
    return (
      <p className="text-sm italic text-slate-400">
        None of the retrieved records carried publication-type metadata, so no
        evidence class can be reported for them.
      </p>
    );
  }

  return (
    <div className="space-y-5">
      <div className="rounded-md border border-slate-200 bg-slate-50 px-4 py-3">
        <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">
          Denominator for every count below
        </p>
        <p className="mt-1 text-sm leading-relaxed text-slate-700">
          {strength.denominator}
        </p>
        {!strength.reconciles && (
          <p className="mt-1 text-xs font-medium text-red-700">
            These class counts do not sum to the stated total. Treat the table as
            unverified until the split is resolved.
          </p>
        )}
      </div>

      <div className="rounded-md border border-slate-200 bg-slate-50 px-4 py-3">
        <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">
          Automated, preliminary interpretation
        </p>
        <p className="mt-1 text-sm leading-relaxed text-slate-700">
          {strength.interpretation}
        </p>
      </div>

      <BarBreakdown
        data={strength.categories.map((c) => ({
          label: c.label,
          count: c.count,
          // The catch-all is not a finding, so it must not read as a class.
          color: c.key === UNCLASSIFIED_KEY ? "#d2d8e0" : "#0d9488",
        }))}
        unit="records"
        rotated
        ariaLabel="Retrieved records by evidence class"
        activeLabel={
          strength.categories.find((c) => c.key === open)?.label ?? null
        }
        onBarClick={(label) => {
          const hit = strength.categories.find((c) => c.label === label);
          if (hit) setOpen(open === hit.key ? null : hit.key);
        }}
      />

      <p className="text-[11px] text-slate-500">
        Select a bar, or a class below, to list the individual records counted in
        it. Every record shows the publication type its source reported.
      </p>

      <ul className="divide-y divide-slate-100 rounded-lg border border-slate-200">
        {strength.categories.map((category) => {
          const expanded = open === category.key;
          return (
            <li key={category.key}>
              <button
                type="button"
                onClick={() => setOpen(expanded ? null : category.key)}
                aria-expanded={expanded}
                className="flex w-full items-center gap-3 px-4 py-3 text-left hover:bg-slate-50"
              >
                <span className="inline-block w-6 shrink-0 text-right text-sm font-semibold text-teal-700">
                  {category.count}
                </span>
                <span className="flex-1">
                  <span className="block text-sm font-medium text-slate-800">
                    {category.label}
                  </span>
                  <span className="block text-[11px] text-slate-500">
                    Counted in {category.unit}s — {category.criteria}
                  </span>
                </span>
                <span className="shrink-0 text-xs text-slate-400">
                  {expanded ? "Hide" : "Inspect"}
                </span>
              </button>
              {expanded && (
                <ul className="space-y-1 bg-slate-50 px-4 pb-3 pt-1">
                  {category.records.length === 0 ? (
                    <li className="text-xs italic text-slate-400">
                      No records listed.
                    </li>
                  ) : (
                    category.records.map((record, i) => (
                      <li
                        key={i}
                        className="break-words text-[11px] leading-relaxed text-slate-600"
                      >
                        {record}
                      </li>
                    ))
                  )}
                </ul>
              )}
            </li>
          );
        })}
      </ul>

      {strength.study_design_counts.length > 0 && (
        <div>
          <p className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-500">
            Study designs, each with the denominator it is counted against
          </p>
          <ul className="divide-y divide-slate-100 rounded-lg border border-slate-200">
            {strength.study_design_counts.map((design) => (
              <li key={design.label} className="px-4 py-2.5">
                <p className="text-sm font-medium text-slate-800">
                  <span className="mr-2 inline-block w-6 text-right font-semibold text-teal-700">
                    {design.count}
                  </span>
                  {design.label}
                </p>
                <p className="mt-0.5 text-[11px] leading-relaxed text-slate-500">
                  {design.definition} Denominator: {design.denominator}
                </p>
              </li>
            ))}
          </ul>
          <p className="mt-1.5 text-[11px] text-slate-500">
            A design tally is a different cut of the same records, not an addition
            to the classes above. “Real-world” here means the source described the
            study as real-world, observational or registry-based; it is not a
            verdict on the design.
          </p>
        </div>
      )}

      <div>
        <p className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-500">
          Limitations of this summary
        </p>
        <ul className="space-y-1.5">
          {strength.limitations.map((limitation, i) => (
            <li key={i} className="flex gap-2 text-xs text-slate-600">
              <span className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full bg-slate-300" />
              <span className="leading-relaxed">{limitation}</span>
            </li>
          ))}
        </ul>
      </div>

      <p className="text-[11px] italic text-slate-400">
        A large number of publications in a class does not make the evidence
        strong. This panel counts retrieved records; it does not judge their
        quality, and no numeric evidence score is computed or displayed.
      </p>
    </div>
  );
}
