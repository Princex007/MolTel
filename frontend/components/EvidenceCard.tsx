import type { EvidenceItem } from "@/lib/api";
import EvidenceBadge from "./EvidenceBadge";

interface EvidenceCardProps {
  item: EvidenceItem;
}

const SOURCE_COLORS: Record<string, string> = {
  PubMed: "bg-blue-50 text-blue-700 border-blue-200",
  EuropePMC: "bg-teal-50 text-teal-700 border-teal-200",
  openFDA: "bg-orange-50 text-orange-700 border-orange-200",
};

export default function EvidenceCard({ item }: EvidenceCardProps) {
  const displayAuthors =
    item.authors.length > 3
      ? `${item.authors.slice(0, 3).join(", ")} et al.`
      : item.authors.join(", ");

  const journal =
    typeof item.metadata?.journal === "string" ? item.metadata.journal : null;

  const sourceClass =
    SOURCE_COLORS[item.source] ?? "bg-slate-50 text-slate-600 border-slate-200";

  return (
    <article className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
      {/* Title */}
      <div className="mb-2">
        {item.url ? (
          <a
            href={item.url}
            target="_blank"
            rel="noopener noreferrer"
            className="text-sm font-semibold text-indigo-700 hover:underline"
          >
            {item.title ?? "Untitled"}
          </a>
        ) : (
          <span className="text-sm font-semibold text-slate-800">
            {item.title ?? "Untitled"}
          </span>
        )}
      </div>

      {/* Meta row */}
      <div className="mb-3 flex flex-wrap items-center gap-2 text-xs text-slate-500">
        {displayAuthors && <span>{displayAuthors}</span>}
        {item.year && (
          <>
            <span aria-hidden="true">·</span>
            <span>{item.year}</span>
          </>
        )}
        {journal && (
          <>
            <span aria-hidden="true">·</span>
            <span className="italic">{journal}</span>
          </>
        )}
      </div>

      {/* Badges */}
      <div className="mb-3 flex flex-wrap gap-1.5">
        <EvidenceBadge evidenceType={item.evidence_type} />
        <span
          className={`inline-flex items-center rounded border px-2 py-0.5 text-xs font-medium ${sourceClass}`}
        >
          {item.source}
        </span>
      </div>

      {/* Abstract */}
      {item.abstract && (
        <p className="line-clamp-3 text-xs leading-relaxed text-slate-600">
          {item.abstract}
        </p>
      )}
    </article>
  );
}
