import type { ValidationReport } from "@/lib/api";

/**
 * The pre-publication gate, published with the dossier it checked.
 *
 * The narrative is written by a model, so a claim that contradicts a retrieved
 * record is named here rather than silently rewritten — the reader has to see the
 * disagreement, not a smoothed-over version of it.
 */
export default function ValidationPanel({ report }: { report: ValidationReport }) {
  return (
    <div className="space-y-3">
      <div
        className={`rounded-lg border px-4 py-3 text-[11px] leading-relaxed ${
          report.blocked
            ? "border-red-300 bg-red-50 text-red-800"
            : report.warnings > 0
            ? "border-amber-300 bg-amber-50 text-amber-900"
            : "border-emerald-200 bg-emerald-50 text-emerald-800"
        }`}
      >
        <p className="text-[10px] font-semibold uppercase tracking-wider">
          {report.blocked
            ? "Publication blocked by the validation gate"
            : report.warnings > 0
            ? "Published with warnings"
            : "No claim contradicted a retrieved record"}
        </p>
        <p className="mt-1">
          {report.errors} error(s), {report.warnings} warning(s) across{" "}
          {report.rules_run.length} rules and {report.checked_fields.length} narrative
          field(s). {report.note}
        </p>
      </div>

      {report.findings.length > 0 && (
        <ul className="space-y-2">
          {report.findings.map((f, i) => (
            <li
              key={`${f.rule}-${i}`}
              className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-[11px] leading-relaxed"
            >
              <p className="flex flex-wrap items-center gap-2">
                <span
                  className={`rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase ${
                    f.severity === "error"
                      ? "bg-red-100 text-red-700"
                      : "bg-amber-100 text-amber-800"
                  }`}
                >
                  {f.severity}
                </span>
                <span className="font-mono text-[10px] text-slate-500">{f.rule}</span>
                <span className="text-slate-500">{f.field}</span>
              </p>
              {f.quote && (
                <p className="mt-1 border-l-2 border-slate-200 pl-2 italic text-slate-700">
                  “{f.quote}”
                </p>
              )}
              {f.expected && (
                <p className="mt-1 text-slate-600">
                  <span className="font-semibold">Source states: </span>
                  {f.expected}
                </p>
              )}
              {f.observed && (
                <p className="text-slate-600">
                  <span className="font-semibold">Report says: </span>
                  {f.observed}
                </p>
              )}
              {f.suggested_correction && (
                <p className="text-slate-600">
                  <span className="font-semibold">To resolve: </span>
                  {f.suggested_correction}
                </p>
              )}
              {f.source_ref && (
                <a
                  href={f.source_ref}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-[11px] text-blue-700 underline"
                >
                  {f.source_ref}
                </a>
              )}
            </li>
          ))}
        </ul>
      )}

      <p className="text-[10px] leading-relaxed text-slate-500">
        Rules run: {report.rules_run.join(", ")}. Checked fields:{" "}
        {report.checked_fields.join(", ") || "none"}.
        {report.generated_at && ` Gate run ${report.generated_at}.`} The gate reads the
        retrieved records only; it never changes a claim and never supplies a value a
        source did not state.
      </p>
    </div>
  );
}
