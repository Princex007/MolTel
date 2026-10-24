import type { EvidenceType } from "@/lib/api";

interface EvidenceBadgeProps {
  evidenceType: EvidenceType | string;
}

const TYPE_CONFIG: Record<
  string,
  { label: string; className: string }
> = {
  clinical: {
    label: "Clinical study",
    className: "bg-green-50 text-green-800 border border-green-300",
  },
  randomized_controlled_trial: {
    label: "Randomized controlled trial",
    className: "bg-emerald-50 text-emerald-800 border border-emerald-300",
  },
  systematic_review: {
    label: "Systematic review / meta-analysis",
    className: "bg-teal-50 text-teal-800 border border-teal-300",
  },
  observational: {
    label: "Observational",
    className: "bg-teal-50 text-teal-800 border border-teal-300",
  },
  case_report: {
    label: "Case report",
    className: "bg-cyan-50 text-cyan-800 border border-cyan-300",
  },
  animal: {
    label: "Animal",
    className: "bg-yellow-50 text-yellow-800 border border-yellow-300",
  },
  cellular: {
    label: "Cellular",
    className: "bg-blue-50 text-blue-800 border border-blue-300",
  },
  biochemical: {
    label: "Biochemical",
    className: "bg-purple-50 text-purple-800 border border-purple-300",
  },
  computational: {
    label: "Computational",
    className: "bg-gray-100 text-gray-700 border border-gray-300",
  },
  literature_review: {
    label: "Narrative review",
    className: "bg-slate-100 text-slate-700 border border-slate-300",
  },
  editorial: {
    label: "Editorial / comment",
    className: "bg-amber-50 text-amber-800 border border-amber-300",
  },
  correction_or_retraction: {
    label: "Correction / retraction notice",
    className: "bg-rose-50 text-rose-800 border border-rose-300",
  },
  other: {
    label: "Not classified by source",
    className: "bg-slate-50 text-slate-500 border border-dashed border-slate-300",
  },
  regulatory: {
    label: "Regulatory",
    className: "bg-orange-50 text-orange-800 border border-orange-300",
  },
  AI_hypothesis: {
    label: "AI Hypothesis",
    className:
      "bg-red-50 text-red-700 border border-red-400 border-dashed",
  },
};

export default function EvidenceBadge({ evidenceType }: EvidenceBadgeProps) {
  const config = TYPE_CONFIG[evidenceType] ?? {
    label: evidenceType,
    className: "bg-slate-100 text-slate-600 border border-slate-200",
  };

  return (
    <span
      className={`inline-flex items-center rounded px-2 py-0.5 text-xs font-medium ${config.className}`}
    >
      {config.label}
    </span>
  );
}
