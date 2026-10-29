import type { QueryAttributionSummary } from "@/lib/api";

/**
 * Which retrieved trials the registry itself links to the queried product.
 *
 * A registry search matches wording, so a returned record is not automatically a
 * study of the product. Only the first two rows name it among that record's own
 * interventions, and the counts here come from the backend.
 */
export default function TrialAttributionPanel({
  attribution,
}: {
  attribution: QueryAttributionSummary;
}) {
  if (!attribution.applicable) {
    return (
      <div className="mb-4 rounded-lg border border-slate-200 bg-slate-50 px-4 py-3 text-[11px] leading-relaxed text-slate-600">
        <p className="font-semibold uppercase tracking-wider text-slate-500">
          Trial attribution
        </p>
        <p className="mt-1">
          {attribution.reason ??
            "This search mode does not name a product, so trials are not attributed to one."}
        </p>
      </div>
    );
  }

  const named = attribution.records.filter(
    (r) => r.category === "direct" || r.category === "comparator_or_combination"
  );

  return (
    <div className="mb-4 rounded-lg border border-slate-200 bg-white px-4 py-3">
      <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">
        Trials attributed to “{attribution.query}”
      </p>
      <table className="mt-2 w-full text-[11px]">
        <thead>
          <tr className="text-left text-slate-500">
            <th className="py-1 font-medium">Relationship to the query</th>
            <th className="py-1 font-medium">What establishes it</th>
            <th className="py-1 text-right font-medium">Trials</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {attribution.categories.map((c) => (
            <tr key={c.key}>
              <td className="py-1 pr-2 text-slate-700">{c.label}</td>
              <td className="py-1 pr-2 text-slate-500">{c.basis}</td>
              <td className="py-1 text-right font-mono text-slate-800">{c.count}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="mt-2 text-[10px] leading-relaxed text-slate-500">
        {attribution.rule} {attribution.reconciliation_note}{" "}
        {attribution.placebo_or_sham_arms} trial(s) register a placebo or sham arm.{" "}
        {attribution.distinct_investigational_candidates} distinct intervention name(s)
        are typed by the registry as drug, biological, dietary-supplement or
        combination-product interventions.
      </p>
      {named.length > 0 && (
        <details className="mt-2">
          <summary className="cursor-pointer text-[10px] font-semibold uppercase tracking-wider text-slate-500">
            Trials naming the queried product ({named.length})
          </summary>
          <ul className="mt-1 space-y-1">
            {named.map((r) => (
              <li key={r.nct_id} className="text-[11px] leading-snug text-slate-600">
                <span className="font-mono">{r.nct_id}</span>{" "}
                {r.source_url ? (
                  <a
                    href={r.source_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-blue-700 underline"
                  >
                    {r.title ?? "registry record"}
                  </a>
                ) : (
                  r.title ?? "registry record"
                )}{" "}
                — {r.matched_interventions.join(", ")}
                {r.registry_roles.length ? ` (${r.registry_roles.join(", ")})` : ""}
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}
