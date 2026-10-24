"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type {
  EvidenceItem,
  LiteratureFilters,
  LiteratureView,
  LiteratureViewResult,
} from "@/lib/api";
import { requestLiteratureView } from "@/lib/api";
import EvidenceBadge from "./EvidenceBadge";

const VIEWS: { key: LiteratureView; label: string; hint: string }[] = [
  {
    key: "most_relevant",
    label: "Most relevant",
    hint: "Query words in the title and abstract, scaled by the design the source reports.",
  },
  {
    key: "latest",
    label: "Latest",
    hint: "The publication date each source states. An indexing date never decides this.",
  },
  {
    key: "strongest_evidence",
    label: "Strongest evidence",
    hint: "The study design the source reports, strongest design first. Not a score for any paper.",
  },
  {
    key: "reviews_guidelines",
    label: "Reviews & guidelines",
    hint: "Only records whose own reported types name a review, guideline or meta-analysis.",
  },
];

const PAGE = 15;

interface Props {
  items: EvidenceItem[];
  /** The query these records were retrieved for; the view ranks against it. */
  query: string;
  /** A subtype the list is already scoped to, shown so the scope is not lost. */
  scopeLabel?: string | null;
  /** Target names retrieved for this query, offered as a relevance filter. */
  targetTerms?: string[];
}

function linkLabel(link: string): string {
  if (link.includes("pubmed.ncbi.nlm.nih.gov")) return "PubMed";
  if (link.includes("europepmc.org")) return "Europe PMC";
  if (link.includes("/pmc/articles/")) return "PMC";
  if (link.includes("doi.org")) return "Publisher DOI";
  return "Source";
}

/** A date exactly as the source stated it, with the precision it stated. */
function PublishedDate({ item }: { item: EvidenceItem }) {
  if (!item.published_on) {
    return <span className="text-slate-400">no date reported</span>;
  }
  return (
    <span title={`The source states a ${item.published_precision ?? "year"} only`}>
      {item.published_on}
      {item.published_precision && item.published_precision !== "day" ? (
        <span className="text-slate-400"> ({item.published_precision})</span>
      ) : null}
    </span>
  );
}

export default function LiteratureTable({
  items,
  query,
  scopeLabel = null,
  targetTerms = [],
}: Props) {
  const [view, setView] = useState<LiteratureView>("most_relevant");
  const [filters, setFilters] = useState<LiteratureFilters>({});
  const [result, setResult] = useState<LiteratureViewResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showWhy, setShowWhy] = useState(false);
  const [visible, setVisible] = useState(PAGE);
  const requestId = useRef(0);

  // The parent rebuilds this array on every render, so the records are read
  // through a ref and a re-request is keyed on their content instead.
  const itemsRef = useRef(items);
  itemsRef.current = items;
  const itemsKey = useMemo(
    () => items.map((item) => `${item.source}:${item.id ?? item.url ?? item.title}`).join("|"),
    [items]
  );

  const refresh = useCallback(async () => {
    const id = ++requestId.current;
    try {
      const next = await requestLiteratureView(
        itemsRef.current,
        query,
        view,
        filters
      );
      if (id === requestId.current) {
        setResult(next);
        setError(null);
      }
    } catch (err) {
      if (id === requestId.current) {
        setError(err instanceof Error ? err.message : "Could not re-order this list.");
      }
    }
  }, [itemsKey, query, view, filters]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    setVisible(PAGE);
  }, [view, filters]);

  const shown = result?.items ?? items;
  const facets = useMemo(() => {
    const byField = new Map<string, { value: string; count: number }[]>();
    (result?.facets ?? []).forEach((facet) => {
      const list = byField.get(facet.field) ?? [];
      list.push({ value: facet.value, count: facet.count });
      byField.set(facet.field, list);
    });
    return byField;
  }, [result]);

  const set = (patch: Partial<LiteratureFilters>) => {
    setFilters((current) => ({ ...current, ...patch }));
  };

  const selectClass =
    "rounded border border-slate-300 bg-white px-2 py-1 text-xs text-slate-700";

  if (items.length === 0) {
    return (
      <p className="py-6 text-center text-sm text-slate-400">
        No literature found.
      </p>
    );
  }

  return (
    <div>
      {/* Views */}
      <div className="mb-3 flex flex-wrap items-center gap-1.5">
        {VIEWS.map((option) => {
          const active = option.key === view;
          return (
            <button
              key={option.key}
              type="button"
              onClick={() => setView(option.key)}
              title={option.hint}
              aria-pressed={active}
              className={`rounded border px-2.5 py-1 text-xs font-medium transition-colors ${
                active
                  ? "border-indigo-500 bg-indigo-600 text-white"
                  : "border-slate-300 bg-white text-slate-700 hover:bg-slate-50"
              }`}
            >
              {option.label}
            </button>
          );
        })}
        <button
          type="button"
          onClick={() => setShowWhy((current) => !current)}
          aria-pressed={showWhy}
          className={`ml-auto rounded border px-2.5 py-1 text-xs font-medium ${
            showWhy
              ? "border-emerald-500 bg-emerald-50 text-emerald-700"
              : "border-slate-300 bg-white text-slate-600 hover:bg-slate-50"
          }`}
        >
          {showWhy ? "Hide ranking reasons" : "Show why each record is here"}
        </button>
      </div>

      <p className="mb-3 text-[11px] leading-relaxed text-slate-500">
        <span className="font-semibold text-slate-700">
          {result?.label ?? "Most relevant"}:
        </span>{" "}
        {result?.rule ??
          "Ordering rule unavailable — the list below is the order the search returned."}
        {scopeLabel ? (
          <>
            {" "}
            Already scoped to the subtype “{scopeLabel}”: only records whose own
            wording names it are in this list.
          </>
        ) : null}
      </p>

      {/* Filters */}
      <div className="mb-3 flex flex-wrap items-end gap-x-4 gap-y-2 rounded-lg border border-slate-200 bg-slate-50 p-2.5">
        <label className="flex flex-col gap-1 text-[10px] font-semibold uppercase tracking-wider text-slate-500">
          Published from
          <input
            type="text"
            inputMode="numeric"
            placeholder="2020"
            value={filters.published_from ?? ""}
            onChange={(event) => set({ published_from: event.target.value || null })}
            className={`${selectClass} w-20`}
          />
        </label>
        <label className="flex flex-col gap-1 text-[10px] font-semibold uppercase tracking-wider text-slate-500">
          to
          <input
            type="text"
            inputMode="numeric"
            placeholder="2024"
            value={filters.published_to ?? ""}
            onChange={(event) => set({ published_to: event.target.value || null })}
            className={`${selectClass} w-20`}
          />
        </label>
        <label className="flex flex-col gap-1 text-[10px] font-semibold uppercase tracking-wider text-slate-500">
          Study scope
          <select
            value={filters.study_scope ?? ""}
            onChange={(event) =>
              set({ study_scope: (event.target.value || null) as LiteratureFilters["study_scope"] })
            }
            className={selectClass}
          >
            <option value="">Any</option>
            <option value="clinical">Studies of people</option>
            <option value="preclinical">Animal, cellular or computational</option>
          </select>
        </label>
        <label className="flex flex-col gap-1 text-[10px] font-semibold uppercase tracking-wider text-slate-500">
          Source
          <select
            value={filters.sources?.[0] ?? ""}
            onChange={(event) =>
              set({ sources: event.target.value ? [event.target.value] : [] })
            }
            className={selectClass}
          >
            <option value="">Any</option>
            {(facets.get("source") ?? []).map((option) => (
              <option key={option.value} value={option.value}>
                {option.value} ({option.count})
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-[10px] font-semibold uppercase tracking-wider text-slate-500">
          Publication type
          <select
            value={filters.publication_types?.[0] ?? ""}
            onChange={(event) =>
              set({
                publication_types: event.target.value ? [event.target.value] : [],
              })
            }
            className={selectClass}
          >
            <option value="">Any reported type</option>
            {(facets.get("publication_type") ?? []).map((option) => (
              <option key={option.value} value={option.value}>
                {option.value} ({option.count})
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-[10px] font-semibold uppercase tracking-wider text-slate-500">
          Access
          <select
            value={
              filters.open_access === true
                ? "open"
                : filters.open_access === false
                  ? "closed"
                  : ""
            }
            onChange={(event) =>
              set({
                open_access:
                  event.target.value === "open"
                    ? true
                    : event.target.value === "closed"
                      ? false
                      : null,
              })
            }
            className={selectClass}
          >
            <option value="">Any</option>
            <option value="open">Stated open access</option>
            <option value="closed">Stated not open access</option>
          </select>
        </label>
        {targetTerms.length > 0 ? (
          <label className="flex flex-col gap-1 text-[10px] font-semibold uppercase tracking-wider text-slate-500">
            Target wording
            <select
              value={
                filters.relevance_to_target === true
                  ? "names"
                  : filters.relevance_to_target === false
                    ? "not"
                    : ""
              }
              onChange={(event) =>
                set({
                  relevance_to_target:
                    event.target.value === "names"
                      ? true
                      : event.target.value === "not"
                        ? false
                        : null,
                })
              }
              className={selectClass}
            >
              <option value="">Any</option>
              <option value="names">Names a retrieved target</option>
              <option value="not">Does not name one</option>
            </select>
          </label>
        ) : null}
        {Object.entries(filters).some(
          ([, value]) =>
            value !== null && value !== undefined && !(Array.isArray(value) && value.length === 0)
        ) ? (
          <button
            type="button"
            onClick={() => setFilters({})}
            className="rounded border border-slate-300 bg-white px-2 py-1 text-xs text-slate-600 hover:bg-slate-100"
          >
            Clear filters
          </button>
        ) : null}
      </div>

      {error ? (
        <p className="mb-3 rounded border border-amber-300 bg-amber-50 px-2.5 py-1.5 text-[11px] leading-relaxed text-amber-800">
          {error} The list below is the order the search returned, not a re-ranked view.
        </p>
      ) : null}

      {/* Counts and what each filter removed */}
      {result ? (
        <p className="mb-2 text-[11px] text-slate-600">
          {result.records_shown} of {result.records_received} publication(s) shown.
          {result.exclusions.length > 0 ? (
            <span className="ml-1">
              Removed —{" "}
              {result.exclusions
                .map((exclusion) => `${exclusion.removed} by ${exclusion.label}`)
                .join("; ")}
              .
            </span>
          ) : null}
        </p>
      ) : null}

      {result?.deduplication && result.deduplication.records_merged > 0 ? (
        <p className="mb-3 rounded border border-slate-200 bg-white px-2.5 py-1.5 text-[11px] leading-relaxed text-slate-600">
          <span className="font-semibold text-slate-700">
            {result.deduplication.records_received} records merged into{" "}
            {result.deduplication.publications} publications
          </span>{" "}
          ({result.deduplication.cross_database_merges} across both databases) — matched
          on {result.deduplication.matched_on.join(", ")}. Every source link is kept on
          the merged record. {result.deduplication.rule}
        </p>
      ) : null}

      <div className="overflow-x-auto rounded-lg border border-slate-200">
        <table className="min-w-full divide-y divide-slate-200 bg-white text-sm">
          <thead className="bg-slate-50">
            <tr>
              <th scope="col" className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-slate-500">
                Title
              </th>
              <th scope="col" className="whitespace-nowrap px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-slate-500">
                Published
              </th>
              <th scope="col" className="hidden px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-slate-500 md:table-cell">
                Authors
              </th>
              <th scope="col" className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-slate-500">
                Evidence Type
              </th>
              <th scope="col" className="hidden px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-slate-500 sm:table-cell">
                Source
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {shown.slice(0, visible).map((item, idx) => {
              const identifier = item.pmid
                ? `PMID: ${item.pmid}`
                : item.pmcid
                  ? `PMCID: ${item.pmcid}`
                  : item.doi
                    ? `DOI: ${item.doi}`
                    : null;
              const displayAuthors =
                item.authors.length > 2
                  ? `${item.authors.slice(0, 2).join(", ")} et al.`
                  : item.authors.join(", ");

              return (
                <tr key={`${item.source}:${item.id ?? idx}`} className="align-top hover:bg-slate-50">
                  <td className="max-w-md px-4 py-3">
                    {item.url ? (
                      <a
                        href={item.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="font-medium text-indigo-700 hover:underline line-clamp-2"
                      >
                        {item.title ?? "Untitled"}
                      </a>
                    ) : (
                      <span className="text-slate-800 line-clamp-2">
                        {item.title ?? "Untitled"}
                      </span>
                    )}
                    <span className="mt-0.5 block text-xs text-slate-400">
                      {identifier ?? "no identifier reported"}
                      {item.journal ? ` · ${item.journal}` : ""}
                      {item.publication_types.length > 0 ? (
                        <span title="Exactly as the source reported it">
                          {" "}
                          · {item.publication_types.join("; ")}
                        </span>
                      ) : (
                        <span> · no publication type reported</span>
                      )}
                      {item.open_access === true ? " · open access" : ""}
                    </span>
                    {item.merged_records > 1 ? (
                      <span className="mt-0.5 block text-[11px] text-slate-500">
                        {item.merged_records} records merged (
                        {item.merged_sources.join(", ")}) —{" "}
                        {item.links.length > 0 ? (
                          <span className="whitespace-nowrap">
                            {item.links.map((link, linkIndex) => (
                              <a
                                key={link}
                                href={link}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="text-indigo-600 hover:underline"
                              >
                                {linkLabel(link)}
                                {linkIndex < item.links.length - 1 ? ", " : ""}
                              </a>
                            ))}
                          </span>
                        ) : (
                          "no links carried"
                        )}
                      </span>
                    ) : null}
                    {showWhy && item.rank_reasons.length > 0 ? (
                      <ul className="mt-1.5 space-y-0.5 border-l-2 border-slate-200 pl-2 text-[11px] leading-relaxed text-slate-600">
                        {item.rank_reasons.map((reason) => (
                          <li key={`${reason.source_field}:${reason.label}`}>
                            {reason.label}
                          </li>
                        ))}
                      </ul>
                    ) : null}
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 text-xs text-slate-600">
                    <PublishedDate item={item} />
                    {item.indexed_on ? (
                      <span className="mt-0.5 block text-[10px] text-slate-400">
                        indexed {item.indexed_on} ({item.indexed_field})
                      </span>
                    ) : null}
                  </td>
                  <td className="hidden px-4 py-3 text-xs text-slate-500 md:table-cell">
                    {displayAuthors || "—"}
                  </td>
                  <td className="px-4 py-3">
                    <EvidenceBadge evidenceType={item.evidence_type} />
                  </td>
                  <td className="hidden px-4 py-3 text-xs text-slate-500 sm:table-cell">
                    {item.source}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {shown.length > visible ? (
        <button
          type="button"
          onClick={() => setVisible((current) => current + PAGE)}
          className="mt-2 rounded border border-slate-300 bg-white px-3 py-1 text-xs text-slate-700 hover:bg-slate-50"
        >
          Show {Math.min(PAGE, shown.length - visible)} more of{" "}
          {shown.length} publication(s)
        </button>
      ) : null}

      {result && result.limitations.length > 0 ? (
        <ul className="mt-3 list-disc space-y-1 pl-5 text-[11px] leading-relaxed text-slate-500">
          {result.limitations.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
