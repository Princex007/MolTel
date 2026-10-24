"use client";

import type { ResearchGap } from "@/lib/api";
import ReferenceList from "./ReferenceList";

// "Evidence limitation" restates what the records show; the other three are
// interpretations, so they are styled as suggestions rather than findings.
const EVIDENCE_BASED = "Evidence limitation";

const LABEL_STYLES: Record<string, string> = {
  "Evidence limitation": "bg-slate-100 text-slate-700",
  "Potential research gap": "bg-amber-50 text-amber-800",
  "Suggested research question": "bg-indigo-50 text-indigo-700",
  "Hypothesis requiring validation": "bg-purple-50 text-purple-700",
};

function Field({ label, value }: { label: string; value: string | null }) {
  if (!value) return null;
  return (
    <p className="mt-1.5 text-xs leading-relaxed text-slate-700">
      <span className="font-semibold text-slate-500">{label}: </span>
      {value}
    </p>
  );
}

export default function ResearchGapPanel({
  gaps,
  aiSynthesized,
}: {
  gaps: ResearchGap[];
  aiSynthesized: boolean;
}) {
  if (!aiSynthesized) {
    return (
      <p className="rounded-md border border-dashed border-slate-300 px-4 py-5 text-center text-sm text-slate-600">
        Gap analysis was not performed: it requires AI synthesis, which was
        unavailable for this query. The evidence gaps section above lists only
        what the retrieval itself was missing.
      </p>
    );
  }

  if (gaps.length === 0) {
    return (
      <p className="rounded-md border border-dashed border-slate-300 px-4 py-5 text-center text-sm text-slate-600">
        The synthesis did not identify a gap it could support with the retrieved
        records. This does not mean the topic is fully studied.
      </p>
    );
  }

  return (
    <div className="space-y-4">
      <p className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs leading-relaxed text-amber-900">
        Suggestions, not findings. Each item describes what the{" "}
        <span className="font-semibold">retrieved</span> records cover. Absence
        from this retrieval is not absence from the literature.
      </p>

      <ul className="space-y-3">
        {gaps.map((gap, i) => {
          const label = gap.label ?? "Suggested research question";
          const fromEvidence = label === EVIDENCE_BASED;
          return (
            <li
              key={i}
              className="rounded-lg border border-slate-200 bg-white p-4"
            >
              <div className="mb-2 flex flex-wrap items-center gap-2">
                <span
                  className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${
                    LABEL_STYLES[label] ?? "bg-slate-100 text-slate-700"
                  }`}
                >
                  {label}
                </span>
                {gap.confidence && (
                  <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] text-slate-600">
                    Confidence it is underexplored: {gap.confidence}
                  </span>
                )}
                <span className="text-[10px] italic text-slate-400">
                  {fromEvidence
                    ? "Observation from the retrieved records"
                    : "AI-generated suggestion"}
                </span>
              </div>

              <p className="text-sm font-semibold leading-snug text-slate-800">
                {gap.question ?? "Unstated question"}
              </p>

              <Field label="Retrieved evidence" value={gap.current_evidence} />
              <Field label="Remains uncertain" value={gap.uncertainty} />
              <Field label="Why it could matter" value={gap.why_it_matters} />
              <Field label="Suggested next step" value={gap.next_step} />

              <ReferenceList references={gap.references} />
            </li>
          );
        })}
      </ul>
    </div>
  );
}
