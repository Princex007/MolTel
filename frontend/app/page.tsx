"use client";

import { useRouter } from "next/navigation";
import SearchBar from "@/components/SearchBar";
import type { SearchMode } from "@/lib/api";

export default function HomePage() {
  const router = useRouter();

  function handleSearch(query: string, mode: SearchMode) {
    router.push(
      `/dossier?query=${encodeURIComponent(query)}&mode=${mode}`
    );
  }

  return (
    <div className="flex min-h-[calc(100vh-3.5rem)] flex-col">
      {/* Hero */}
      <section className="flex flex-1 flex-col items-center justify-center px-4 py-16 sm:px-6 lg:px-8">
        <div className="w-full max-w-2xl">
          {/* Headline */}
          <div className="mb-10 text-center">
            <div className="mb-3 inline-flex items-center gap-2 rounded-full border border-indigo-200 bg-indigo-50 px-3 py-1 text-xs font-medium text-indigo-700">
              <span className="h-1.5 w-1.5 rounded-full bg-indigo-600" />
              Powered by public scientific APIs
            </div>
            <h1 className="mb-3 text-4xl font-bold tracking-tight text-slate-900 sm:text-5xl">
              MOLTEL
            </h1>
            <p className="text-base text-slate-500">
              Evidence-backed pharmaceutical research intelligence
            </p>
          </div>

          {/* Search */}
          <SearchBar onSubmit={handleSearch} />
        </div>
      </section>

      {/* How it works */}
      <section className="border-t border-slate-200 bg-white px-4 py-10 sm:px-6 lg:px-8">
        <div className="mx-auto max-w-4xl">
          <h2 className="mb-6 text-center text-xs font-semibold uppercase tracking-widest text-slate-400">
            How it works
          </h2>
          <div className="grid grid-cols-1 gap-6 sm:grid-cols-3">
            {[
              {
                step: "1",
                title: "Choose what to search",
                body: "A compound, a disease or subtype, or a target. The mode decides which sources can answer it.",
              },
              {
                step: "2",
                title: "Retrieve",
                body: "PubMed, ClinicalTrials.gov, UniProt and Europe PMC are queried in parallel, plus PubChem and openFDA for a compound, or the disease ontology for a disease. A source the mode does not query is reported as not queried, never as a failure.",
              },
              {
                step: "3",
                title: "Synthesize",
                body: "Evidence is normalized, ranked, and summarized into a structured research dossier.",
              },
            ].map(({ step, title, body }) => (
              <div
                key={step}
                className="flex gap-4 rounded-lg border border-slate-100 bg-slate-50 p-4"
              >
                <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-indigo-600 text-xs font-bold text-white">
                  {step}
                </span>
                <div>
                  <h3 className="mb-1 text-sm font-semibold text-slate-800">
                    {title}
                  </h3>
                  <p className="text-xs leading-relaxed text-slate-500">{body}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>
    </div>
  );
}
