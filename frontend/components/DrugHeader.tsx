import Link from "next/link";
import type { SearchMode } from "@/lib/api";

interface DrugHeaderProps {
  query: string;
  compoundName?: string | null;
  status: "success" | "partial" | "error" | string;
  /** Which kind of entity was searched. Shown so the reader knows what MolTel
   *  was asked for, and therefore which sources could answer it. */
  mode?: SearchMode;
}

const MODE_LABEL: Record<SearchMode, string> = {
  compound: "Compound or development code",
  disease: "Disease or subtype",
  target: "Target, gene or protein",
};

const STATUS_CONFIG = {
  success: {
    label: "Complete",
    className: "bg-green-50 text-green-800 border border-green-300",
  },
  partial: {
    label: "Partial",
    className: "bg-yellow-50 text-yellow-800 border border-yellow-300",
  },
  error: {
    label: "Error",
    className: "bg-red-50 text-red-800 border border-red-300",
  },
};

export default function DrugHeader({
  query,
  compoundName,
  status,
  mode = "compound",
}: DrugHeaderProps) {
  const cfg =
    STATUS_CONFIG[status as keyof typeof STATUS_CONFIG] ?? STATUS_CONFIG.partial;

  const displayName = compoundName ?? query;

  return (
    <header className="rounded-lg border border-slate-200 bg-white px-6 py-6 shadow-sm">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        {/* Left: title block */}
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-slate-900 sm:text-3xl">
            {displayName.toUpperCase()}
          </h1>
          <p className="mt-1 text-sm text-slate-500">Research Dossier</p>
          <p className="mt-1.5 text-xs text-slate-500">
            Searching as:{" "}
            <span className="font-medium text-slate-700">{MODE_LABEL[mode]}</span>
          </p>
          {compoundName && compoundName !== query && (
            <p className="mt-1 text-xs text-slate-400">
              Query: <span className="italic">{query}</span>
            </p>
          )}
        </div>

        {/* Right: badge + new search */}
        <div className="flex flex-col items-start gap-3 sm:items-end">
          <span
            className={`inline-flex items-center rounded px-3 py-1 text-xs font-semibold ${cfg.className}`}
          >
            {cfg.label}
          </span>
          <Link
            href="/"
            className="text-xs text-indigo-600 hover:text-indigo-800 hover:underline"
          >
            ← New Search
          </Link>
        </div>
      </div>
    </header>
  );
}
