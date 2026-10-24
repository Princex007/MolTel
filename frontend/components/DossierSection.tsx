interface DossierSectionProps {
  title: string;
  children?: React.ReactNode;
  isEmpty?: boolean;
  /** One-line explanation of what the section is and is not. */
  description?: string;
  /**
   * What to say when there is nothing to show. An empty section must never read
   * as a finding, so callers state which analysis was skipped.
   */
  emptyMessage?: string;
  /** A statement about what this section does and does not cover right now,
   *  such as when another section of the page is filtered to a narrower subset. */
  note?: React.ReactNode;
}

export default function DossierSection({
  title,
  children,
  isEmpty,
  description,
  emptyMessage = "No data available for this section.",
  note,
}: DossierSectionProps) {
  return (
    <section className="scroll-mt-20 rounded-lg border border-slate-200 bg-white shadow-sm">
      {/* Section header */}
      <div className="border-b border-slate-100 px-6 py-4">
        <h2 className="text-sm font-semibold uppercase tracking-widest text-slate-500">
          {title}
        </h2>
        {description && (
          <p className="mt-1.5 text-[11px] leading-relaxed text-slate-400">
            {description}
          </p>
        )}
      </div>

      {/* Section body */}
      <div className="px-6 py-5">
        {note && (
          <p className="mb-4 rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-[11px] leading-relaxed text-slate-600">
            {note}
          </p>
        )}
        {isEmpty || !children ? (
          <p className="text-sm italic text-slate-400">{emptyMessage}</p>
        ) : (
          children
        )}
      </div>
    </section>
  );
}
