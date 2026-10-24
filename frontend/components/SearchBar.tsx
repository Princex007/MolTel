"use client";

import { useState, type KeyboardEvent } from "react";
import type { SearchMode } from "@/lib/api";

/**
 * The mode is chosen explicitly rather than guessed, because it decides which
 * sources MolTel queries — and a source it did not query is reported as skipped,
 * never as a failure or as an empty result.
 */
const MODES: {
  value: SearchMode;
  label: string;
  hint: string;
  placeholder: string;
  examples: string[];
}[] = [
  {
    value: "compound",
    label: "Compound or code",
    hint: "A drug, its brand or generic name, or a development code",
    placeholder: "Drug, brand or development code...",
    examples: ["Metformin", "Pembrolizumab", "BMS-986165"],
  },
  {
    value: "disease",
    label: "Disease or subtype",
    hint: "A condition, or a subtype of one. Results are grouped by subtype",
    placeholder: "Disease or subtype, e.g. lung cancer or NSCLC...",
    examples: ["lung cancer", "Alzheimer disease", "type 2 diabetes mellitus"],
  },
  {
    value: "target",
    label: "Target or gene",
    hint: "A protein, gene or biological target",
    placeholder: "Target, gene or protein, e.g. PDCD1...",
    examples: ["PDCD1", "ACE2", "TRPC5"],
  },
];

interface SearchBarProps {
  onSubmit: (query: string, mode: SearchMode) => void;
  isLoading?: boolean;
  initialMode?: SearchMode;
}

export default function SearchBar({
  onSubmit,
  isLoading,
  initialMode = "compound",
}: SearchBarProps) {
  const [value, setValue] = useState("");
  const [mode, setMode] = useState<SearchMode>(initialMode);
  const active = MODES.find((m) => m.value === mode) ?? MODES[0];

  function handleSubmit() {
    const q = value.trim();
    if (!q || isLoading) return;
    onSubmit(q, mode);
  }

  function handleKey(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter") handleSubmit();
  }

  function handleExample(q: string) {
    setValue(q);
    onSubmit(q, mode);
  }

  return (
    <div className="w-full">
      {/* Search mode */}
      <div
        role="radiogroup"
        aria-label="What to search for"
        className="mb-3 flex flex-wrap gap-2"
      >
        {MODES.map((m) => {
          const selected = m.value === mode;
          return (
            <button
              key={m.value}
              type="button"
              role="radio"
              aria-checked={selected}
              onClick={() => setMode(m.value)}
              disabled={isLoading}
              title={m.hint}
              className={`rounded-lg border px-3 py-2 text-xs font-semibold shadow-sm transition focus:outline-none focus:ring-2 focus:ring-indigo-500/40 disabled:cursor-not-allowed disabled:opacity-60 ${
                selected
                  ? "border-indigo-600 bg-indigo-600 text-white"
                  : "border-slate-300 bg-white text-slate-600 hover:border-indigo-300 hover:text-indigo-700"
              }`}
            >
              {m.label}
            </button>
          );
        })}
      </div>
      <p className="mb-2 text-xs text-slate-500">{active.hint}</p>

      {/* Search input row */}
      <div className="flex gap-2">
        <input
          type="search"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={handleKey}
          placeholder={active.placeholder}
          disabled={isLoading}
          aria-label="Research query"
          className="flex-1 rounded-lg border border-slate-300 bg-white px-4 py-3 text-sm text-slate-900 placeholder-slate-400 shadow-sm transition focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-500/30 disabled:cursor-not-allowed disabled:opacity-60"
        />
        <button
          type="button"
          onClick={handleSubmit}
          disabled={isLoading || !value.trim()}
          className="shrink-0 rounded-lg bg-indigo-600 px-5 py-3 text-sm font-semibold text-white shadow-sm transition hover:bg-indigo-700 focus:outline-none focus:ring-2 focus:ring-indigo-500/50 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {isLoading ? (
            <span className="flex items-center gap-2">
              <span className="block h-3.5 w-3.5 rounded-full border-2 border-white border-t-transparent animate-spin" />
              Generating...
            </span>
          ) : (
            "Generate Dossier"
          )}
        </button>
      </div>

      {/* Example queries for the selected mode */}
      <div className="mt-4">
        <p className="mb-2 text-xs font-medium uppercase tracking-wider text-slate-400">
          Examples for {active.label.toLowerCase()}
        </p>
        <div className="flex flex-wrap gap-2">
          {active.examples.map((q) => (
            <button
              key={q}
              type="button"
              onClick={() => handleExample(q)}
              disabled={isLoading}
              className="rounded-full border border-slate-200 bg-white px-3 py-1.5 text-xs text-slate-600 shadow-sm transition hover:border-indigo-300 hover:bg-indigo-50 hover:text-indigo-700 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {q}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
