"use client";

import type { Contradiction, ContradictoryFindings } from "@/lib/api";
import { ReferenceCitation } from "./ReferenceList";

const CLASSIFICATION_LABELS: Record<string, string> = {
  generally_consistent: "Generally consistent findings",
  potentially_conflicting: "Potentially conflicting findings",
  different_experimental_contexts: "Different experimental contexts",
  insufficient_evidence_to_compare: "Insufficient evidence to compare",
};

function classificationLabel(value: string | null): string {
  if (!value) return "Not classified";
  return (
    CLASSIFICATION_LABELS[value.toLowerCase().replace(/\s+/g, "_")] ??
    value
  );
}

function Field({ label, value }: { label: string; value: string | null }) {
  if (!value) return null;
  return (
    <div>
      <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">
        {label}
      </p>
      <p className="mt-0.5 text-xs leading-relaxed text-slate-700">{value}</p>
    </div>
  );
}

function ContradictionCard({ item }: { item: Contradiction }) {
  return (
    <li className="rounded-lg border border-slate-200 bg-white p-4">
      <p className="text-sm font-semibold text-slate-800">
        {item.claim ?? "Unstated claim"}
      </p>

      <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2">
        <div className="rounded-md border-l-2 border-emerald-400 bg-emerald-50/60 px-3 py-2">
          <p className="text-[10px] font-semibold uppercase tracking-wider text-emerald-700">
            Reported by
          </p>
          <p className="mt-0.5 text-xs leading-relaxed text-slate-700">
            {item.study_a ?? "Not stated in the retrieved record."}
          </p>
        </div>
        <div className="rounded-md border-l-2 border-rose-400 bg-rose-50/60 px-3 py-2">
          <p className="text-[10px] font-semibold uppercase tracking-wider text-rose-700">
            Contrasted by
          </p>
          <p className="mt-0.5 text-xs leading-relaxed text-slate-700">
            {item.study_b ?? "Not stated in the retrieved record."}
          </p>
        </div>
      </div>

      <div className="mt-3 space-y-2.5">
        <Field label="Experimental context" value={item.context_difference} />
        <Field
          label="Possible explanation (interpretation, not a finding)"
          value={item.possible_explanation}
        />
        <Field
          label="Missing for a reliable comparison"
          value={item.missing_information}
        />
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-2 text-[11px]">
        <span className="rounded-full bg-indigo-50 px-2 py-0.5 font-medium text-indigo-700">
          {classificationLabel(item.classification)}
        </span>
        {item.confidence && (
          <span className="rounded-full bg-slate-100 px-2 py-0.5 text-slate-600">
            Confidence: {item.confidence}
          </span>
        )}
      </div>

      {item.citations.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-1.5 border-t border-slate-100 pt-2">
          {item.citations.map((c, i) => (
            <ReferenceCitation key={i} reference={c} index={i} />
          ))}
        </div>
      )}
    </li>
  );
}

export default function ContradictoryFindingsPanel({
  findings,
  aiSynthesized,
}: {
  findings: ContradictoryFindings;
  aiSynthesized: boolean;
}) {
  const count = findings.contradictions.length;

  return (
    <div className="space-y-4">
      {!aiSynthesized && (
        <p className="rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-600">
          This comparison needs AI synthesis and was not performed. The records
          below are shown as retrieved, unassessed.
        </p>
      )}

      {count === 0 ? (
        <p className="rounded-md border border-dashed border-slate-300 px-4 py-5 text-center text-sm text-slate-600">
          {findings.assessment ??
            "No clear contradiction was identified in the retrieved evidence. This does not establish that conflicting evidence does not exist."}
        </p>
      ) : (
        <>
          <p className="text-xs text-slate-600">
            {findings.assessment && (
              <span className="font-medium">{findings.assessment} — </span>
            )}
            {count} potential conflict{count === 1 ? "" : "s"} between records
            that address the same question. Studies measuring different
            outcomes, or using different models, doses or endpoints, are listed
            as different contexts rather than as contradictions.
          </p>
          <ul className="space-y-3">
            {findings.contradictions.map((item, i) => (
              <ContradictionCard key={i} item={item} />
            ))}
          </ul>
        </>
      )}

      <p className="text-[11px] italic text-slate-400">
        Conflicts are reported only where the retrieved records support them. A
        limited retrieval cannot establish that the wider literature agrees.
      </p>
    </div>
  );
}
