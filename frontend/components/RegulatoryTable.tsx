import type { EvidenceItem } from "@/lib/api";

interface RegulatoryTableProps {
  items: EvidenceItem[];
}

export default function RegulatoryTable({ items }: RegulatoryTableProps) {
  if (items.length === 0) {
    return (
      <p className="py-6 text-center text-sm text-slate-400">
        No FDA labelling matched this query.
      </p>
    );
  }

  return (
    <ul className="flex flex-col gap-3">
      {items.map((item, idx) => (
        <li
          key={`${item.metadata?.section ?? "section"}-${item.id ?? idx}`}
          className="rounded-lg border border-slate-200 bg-white"
        >
          <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1 border-b border-slate-100 px-4 py-2">
            <span className="text-xs font-semibold uppercase tracking-wider text-orange-700">
              {String(item.metadata?.section_title ?? item.metadata?.section ?? "Label section")}
            </span>
            <span className="text-xs text-slate-500">
              {String(item.metadata?.drug_name ?? "")}
            </span>
            {item.url && (
              <a
                href={item.url}
                target="_blank"
                rel="noopener noreferrer"
                className="ml-auto text-xs text-indigo-600 hover:underline"
              >
                openFDA record
              </a>
            )}
          </div>
          <p className="px-4 py-3 text-sm leading-relaxed text-slate-700">
            {item.abstract ?? "—"}
          </p>
        </li>
      ))}
      <li className="rounded-md border border-slate-200 bg-slate-50 px-4 py-2 text-xs text-slate-500">
        Label text is quoted from FDA drug labelling. Listed adverse reactions
        are spontaneous reports and are not evidence of causality.
      </li>
    </ul>
  );
}
