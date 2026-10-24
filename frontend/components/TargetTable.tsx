import type { TargetProfile } from "@/lib/api";

interface TargetTableProps {
  targets: TargetProfile[];
}

export default function TargetTable({ targets }: TargetTableProps) {
  if (targets.length === 0) {
    return (
      <p className="py-6 text-center text-sm text-slate-400">
        No protein targets identified.
      </p>
    );
  }

  return (
    <div className="overflow-x-auto rounded-lg border border-slate-200">
      <table className="min-w-full divide-y divide-slate-200 bg-white text-sm">
        <thead className="bg-slate-50">
          <tr>
            <th
              scope="col"
              className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-slate-500"
            >
              Accession
            </th>
            <th
              scope="col"
              className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-slate-500"
            >
              Protein
            </th>
            <th
              scope="col"
              className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-slate-500"
            >
              Gene
            </th>
            <th
              scope="col"
              className="hidden px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-slate-500 sm:table-cell"
            >
              Organism
            </th>
            <th
              scope="col"
              className="hidden px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-slate-500 md:table-cell"
            >
              Function
            </th>
            <th
              scope="col"
              className="hidden px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-slate-500 lg:table-cell"
            >
              Location
            </th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {targets.map((target) => (
            <tr
              key={target.accession}
              className="hover:bg-slate-50 transition-colors"
            >
              <td className="whitespace-nowrap px-4 py-3">
                {target.url ? (
                  <a
                    href={target.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="font-mono text-xs text-indigo-700 hover:underline"
                  >
                    {target.accession}
                  </a>
                ) : (
                  <span className="font-mono text-xs text-slate-700">
                    {target.accession}
                  </span>
                )}
              </td>
              <td className="px-4 py-3 text-slate-800">
                {target.name ?? "—"}
              </td>
              <td className="whitespace-nowrap px-4 py-3 font-mono text-xs text-slate-600">
                {target.gene ?? "—"}
              </td>
              <td className="hidden px-4 py-3 text-xs italic text-slate-500 sm:table-cell">
                {target.organism ?? "—"}
              </td>
              <td className="hidden px-4 py-3 text-xs text-slate-500 md:table-cell">
                <span className="line-clamp-3">
                  {target.function_summary ?? "—"}
                </span>
              </td>
              <td className="hidden px-4 py-3 text-xs text-slate-500 lg:table-cell">
                {target.subcellular_location ?? "—"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
