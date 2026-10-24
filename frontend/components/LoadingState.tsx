"use client";

import { useEffect, useState } from "react";

const STATUS_MESSAGES = [
  "Querying scientific databases...",
  "Retrieving compound data from PubChem...",
  "Searching PubMed and Europe PMC...",
  "Checking clinical trials registry...",
  "Fetching regulatory information...",
  "Normalizing evidence...",
  "Ranking by relevance...",
  "Generating dossier with AI synthesis...",
  "Almost done...",
];

interface LoadingStateProps {
  message?: string;
}

export default function LoadingState({ message }: LoadingStateProps) {
  const [msgIndex, setMsgIndex] = useState(0);
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    if (message) return; // static message — no cycling
    const id = setInterval(() => {
      setMsgIndex((i) => (i + 1) % STATUS_MESSAGES.length);
    }, 2500);
    return () => clearInterval(id);
  }, [message]);

  useEffect(() => {
    const id = setInterval(() => setElapsed((e) => e + 1), 1000);
    return () => clearInterval(id);
  }, []);

  const displayMessage = message ?? STATUS_MESSAGES[msgIndex];

  return (
    <div
      className="flex flex-col items-center justify-center gap-6 py-24"
      role="status"
      aria-label="Loading research dossier"
    >
      {/* Spinner */}
      <div className="relative h-16 w-16">
        <div className="absolute inset-0 rounded-full border-4 border-slate-200" />
        <div className="absolute inset-0 rounded-full border-4 border-indigo-600 spinner-ring" />
      </div>

      {/* Message */}
      <p
        key={displayMessage}
        className="text-sm font-medium text-slate-600 transition-opacity duration-300"
        aria-live="polite"
      >
        {displayMessage}
      </p>

      {!message && (
        <div className="text-center">
          <p className="text-xs text-slate-400" aria-live="off">
            {elapsed}s elapsed
          </p>
          {/* The synthesis step is a single long model call, so it can take the
              best part of a minute without anything being stuck. */}
          {elapsed >= 25 && (
            <p className="mx-auto mt-1 max-w-sm text-[11px] leading-relaxed text-slate-400">
              Still running. The six sources are queried in parallel, then one
              model call writes the synthesis — that step alone can take half a
              minute or more.
            </p>
          )}
        </div>
      )}

      {/* Step dots */}
      <div className="flex gap-1.5" aria-hidden="true">
        {[0, 1, 2].map((i) => (
          <span
            key={i}
            className={`block h-1.5 w-1.5 rounded-full transition-colors duration-500 ${
              i === msgIndex % 3 ? "bg-indigo-600" : "bg-slate-300"
            }`}
          />
        ))}
      </div>
    </div>
  );
}
