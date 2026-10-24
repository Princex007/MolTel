"use client";

import { useCallback, useEffect, useState, Suspense } from "react";
import { useSearchParams } from "next/navigation";
import Link from "next/link";
import {
  fetchDossier,
  type DossierResponse,
  type SearchMode,
  type SourceStatus,
  type EvidenceItem,
} from "@/lib/api";
import { detectSignals } from "@/lib/report";
import LoadingState from "@/components/LoadingState";
import DrugHeader from "@/components/DrugHeader";
import DossierSection from "@/components/DossierSection";
import CompoundCard from "@/components/CompoundCard";
import LiteratureTable from "@/components/LiteratureTable";
import RegulatoryTable from "@/components/RegulatoryTable";
import TargetTable from "@/components/TargetTable";
import EvidenceStrengthPanel from "@/components/EvidenceStrengthPanel";
import ExportControls from "@/components/ExportControls";
import ContradictoryFindingsPanel from "@/components/ContradictoryFindingsPanel";
import ResearchGapPanel from "@/components/ResearchGapPanel";
import DiseaseDashboard from "@/components/disease/DiseaseDashboard";
import { ReferenceCitation } from "@/components/ReferenceList";
import ClinicalTrialDashboard from "@/components/trials/ClinicalTrialDashboard";

// ─── Source status panel ──────────────────────────────────────────────────────

function SourceStatusPanel({
  sources,
  retrievedAt,
  registryRetrievedAt,
}: {
  sources: SourceStatus[];
  retrievedAt: string | null;
  registryRetrievedAt: string | null;
}) {
  const iconFor = (status: string) => {
    if (status === "success") return "✓";
    if (status === "error") return "✗";
    if (status === "skipped") return "⤳";
    return "—";
  };

  const colorFor = (status: string) => {
    if (status === "success") return "text-green-600";
    if (status === "error") return "text-red-500";
    if (status === "skipped") return "text-slate-300";
    return "text-slate-400";
  };

  const labelFor = (status: string) =>
    status === "skipped"
      ? "not queried for this search mode"
      : status === "no_results"
        ? "queried, returned no records"
        : status.replace("_", " ");

  return (
    <div className="rounded-lg border border-slate-200 bg-white px-5 py-4 shadow-sm">
      <p className="mb-3 text-xs font-semibold uppercase tracking-widest text-slate-400">
        Data sources and retrieval metadata
      </p>
      <ul className="grid grid-cols-2 gap-x-6 gap-y-2 sm:grid-cols-3">
        {sources.map((s) => (
          <li key={s.source_name} className="flex items-center gap-2 text-sm">
            <span
              className={`shrink-0 font-bold ${colorFor(s.status)}`}
              aria-label={s.status}
            >
              {iconFor(s.status)}
            </span>
            <span className="text-slate-700">{s.source_name}</span>
            {s.status === "success" && s.count > 0 && (
              <span className="text-xs text-slate-400">({s.count})</span>
            )}
            {(s.status === "skipped" || s.status === "no_results") && (
              <span
                className={`text-xs ${s.status === "skipped" ? "text-slate-400 italic" : "text-slate-400"}`}
                title={s.note ?? labelFor(s.status)}
              >
                {s.note ?? labelFor(s.status)}
              </span>
            )}
            {s.status === "error" && s.error_message && (
              <span
                className="ml-1 truncate text-xs text-red-400"
                title={s.error_message}
              >
                — {s.error_message.slice(0, 40)}
              </span>
            )}
          </li>
        ))}
      </ul>
      <dl className="mt-4 grid grid-cols-1 gap-x-6 gap-y-1 border-t border-slate-100 pt-3 text-[11px] text-slate-500 sm:grid-cols-2">
        <div className="flex gap-1">
          <dt className="font-medium text-slate-600">MolTel retrieval time:</dt>
          <dd>{retrievedAt ? new Date(retrievedAt).toLocaleString() : "unknown"}</dd>
        </div>
        <div className="flex gap-1">
          <dt className="font-medium text-slate-600">Registry retrieval time:</dt>
          <dd>
            {registryRetrievedAt
              ? new Date(registryRetrievedAt).toLocaleString()
              : "not retrieved"}
          </dd>
        </div>
      </dl>
      <p className="mt-2 text-[11px] leading-relaxed text-slate-400">
        Each source is queried independently, so one failure does not invalidate the
        others. A source marked <span className="italic">not queried</span> was not asked
        for this search mode — PubChem and openFDA resolve a product by name, so a disease
        or target query does not consult them. That is not a source failure and is not
        counted as an empty result. A source&apos;s own last-updated date is shown on the
        record itself, separately from when MolTel fetched it.
      </p>
    </div>
  );
}

// ─── Bullet list helper ───────────────────────────────────────────────────────

function BulletList({ text }: { text: string }) {
  const lines = text
    .split(/\n+/)
    .map((l) => l.replace(/^(?:[-•*]\s+|\d+[.)]\s+)/, "").trim())
    .filter(Boolean);

  if (lines.length <= 1) {
    return <p className="text-sm leading-relaxed text-slate-700">{text.trim()}</p>;
  }

  return (
    <ul className="space-y-1.5">
      {lines.map((line, i) => (
        <li key={i} className="flex gap-2 text-sm text-slate-700">
          <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-indigo-400" />
          <span className="leading-relaxed">{line}</span>
        </li>
      ))}
    </ul>
  );
}

// ─── Section navigation ───────────────────────────────────────────────────────

function SectionNav({ ids }: { ids: { id: string; label: string }[] }) {
  return (
    <nav
      aria-label="Dossier sections"
      className="sticky top-0 z-10 -mx-1 overflow-x-auto rounded-lg border border-slate-200 bg-white/95 px-3 py-2 shadow-sm backdrop-blur"
    >
      <ul className="flex gap-1.5 whitespace-nowrap">
        {ids.map(({ id, label }) => (
          <li key={id}>
            <a
              href={`#${id}`}
              className="inline-block rounded-md px-2.5 py-1 text-[11px] font-medium text-slate-600 hover:bg-indigo-50 hover:text-indigo-700"
            >
              {label}
            </a>
          </li>
        ))}
      </ul>
    </nav>
  );
}

// ─── Retrieval and synthesis state banner ─────────────────────────────────────
// Retrieval + synthesis fine shows no banner. The other two states are named
// separately: synthesis unavailable, and retrieval only partly successful.

function StatusBanner({
  data,
  onRetry,
  retrying,
}: {
  data: DossierResponse;
  onRetry: () => void;
  retrying: boolean;
}) {
  const failed = data.sources.filter((s) => s.status === "error");
  const synthesisMissing = !data.ai_synthesized;
  if (data.ai_synthesized && failed.length === 0) return null;

  return (
    <div
      className={`flex flex-wrap items-start gap-3 rounded-lg border px-4 py-3 ${
        synthesisMissing
          ? "border-amber-300 bg-amber-50 text-amber-900"
          : "border-slate-200 bg-slate-50 text-slate-700"
      }`}
    >
      <div className="min-w-[16rem] flex-1">
        <p className="text-sm font-semibold">
          {synthesisMissing
            ? "No AI synthesis — showing retrieved records directly"
            : "Retrieval was partial — the records below are those successfully retrieved"}
        </p>
        <p className="mt-0.5 text-xs leading-relaxed">
          {synthesisMissing
            ? `${data.synthesis_detail ?? "The interpretation layer was unavailable."} The records, source links, tables and charts below are complete as retrieved. Hypotheses, contradiction comparison and gap analysis were not produced, so none is reported here.`
            : `${failed.length} source(s) returned an error: ${failed
                .map((s) => s.source_name)
                .join(", ")}. Charts and tables cover only the records that were retrieved.`}
        </p>
      </div>
      <button
        type="button"
        onClick={onRetry}
        disabled={retrying}
        className="rounded-md border border-current px-3 py-1.5 text-xs font-semibold opacity-80 hover:opacity-100 disabled:opacity-50"
      >
        {retrying ? "Retrying…" : "Retry retrieval and synthesis"}
      </button>
    </div>
  );
}

// ─── Inner dossier content ────────────────────────────────────────────────────

function DossierContent({ query, mode }: { query: string; mode: SearchMode }) {
  const [data, setData] = useState<DossierResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  // A subtype selection filters the records already retrieved for this query —
  // it does not re-query anything, so it is dropped as soon as a new fetch runs.
  const [subtype, setSubtype] = useState<number | null>(null);

  const load = useCallback(() => {
    if (!query) return;
    setLoading(true);
    setError(null);
    fetchDossier(query, mode)
      .then(setData)
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : "Unknown error occurred");
      })
      .finally(() => setLoading(false));
  }, [query, mode]);

  useEffect(() => {
    if (!query) return;
    setData(null);
    setSubtype(null);
    load();
  }, [query, mode, load]);

  if (loading) return <LoadingState />;

  if (error) {
    return (
      <div className="rounded-lg border border-red-200 bg-red-50 px-6 py-8 text-center">
        <p className="mb-2 text-sm font-semibold text-red-700">
          Failed to generate dossier
        </p>
        <p className="mb-4 text-xs text-red-600">{error}</p>
        <div className="flex flex-wrap justify-center gap-4">
          <button
            type="button"
            onClick={load}
            className="text-sm font-medium text-indigo-600 hover:underline"
          >
            Retry this query
          </button>
          <Link
            href="/"
            className="text-sm font-medium text-indigo-600 hover:underline"
          >
            ← Try a different query
          </Link>
        </div>
      </div>
    );
  }

  if (!data) return null;

  const d = data.dossier;
  const signals = detectSignals(data);

  // Raw evidence items drive the tables; openFDA passages are regulatory, not literature.
  const literatureItems: EvidenceItem[] = (data.evidence_items ?? []).filter(
    (item) => item.source_type === "literature"
  );
  const regulatoryItems: EvidenceItem[] = (data.evidence_items ?? []).filter(
    (item) => item.source_type === "regulatory"
  );

  const trialItems = data.clinical_trials ?? [];
  const targetItems = data.targets ?? [];
  const analytics = data.trial_analytics;
  const gaps = d?.research_gap_analysis ?? [];
  const conditions = Array.from(
    new Set(trialItems.flatMap((t) => t.conditions ?? []))
  ).slice(0, 24);

  // One section per purpose, numbered as it is emitted, conditional on what this
  // query actually retrieved. Exports apply the same inclusion rules.
  const parts: { id: string; label: string; node: React.ReactNode }[] = [];

  parts.push({
    id: "summary",
    label: "1 Summary",
    node: (
      <DossierSection
        title="1. Executive Summary"
        emptyMessage="No AI synthesis was produced for this query, so no summary is asserted here. The records retrieved below are complete and are the evidence base a summary would have drawn from."
      >
        {d?.executive_summary && <BulletList text={d.executive_summary} />}
      </DossierSection>
    ),
  });

  const disease = data.disease_analytics;
  const selectedSubtype =
    disease && subtype !== null ? disease.subtypes[subtype] ?? null : null;
  // A subtype selection scopes the record lists inside the disease dashboard.
  // The query-level counts elsewhere on the page stay whole-query, and say so.
  const subtypeScope = selectedSubtype
    ? `The disease dashboard above is scoped to the subtype “${selectedSubtype.label}” — ${selectedSubtype.trial_nct_ids.length} of the ${disease?.trials_considered ?? 0} trials retrieved. Everything in this section covers the whole retrieved set for “${query}”.`
    : "";

  if (disease) {
    const n = parts.length + 1;
    parts.push({
      id: "disease",
      label: `${n} Disease intelligence`,
      node: (
        <DossierSection
          title={`${n}. Disease Intelligence — ${disease.canonical_term}`}
          description="Searched as a disease or subtype. The query is kept exactly as submitted; the term above is what the disease ontology resolved it to, and subtype choices come from standardized concepts plus the condition wording of the records retrieved — not from a fixed list of diseases."
        >
          {/* Without AI synthesis, therapeutic_evidence is a plain listing of the
              condition strings the dashboard below already shows with counts, so it
              is only rendered when it is an actual synthesized statement. */}
          {data.ai_synthesized && d?.therapeutic_evidence && (
            <div className="mb-4">
              <BulletList text={d.therapeutic_evidence} />
            </div>
          )}
          <DiseaseDashboard
            analytics={disease}
            trials={trialItems}
            papers={literatureItems}
            targets={targetItems}
            selected={subtype}
            onSelect={setSubtype}
          />
        </DossierSection>
      ),
    });
  }

  if (!disease && signals.disease) {
    const n = parts.length + 1;
    parts.push({
      id: "disease",
      label: `${n} Disease context`,
      node: (
        <DossierSection
          title={`${n}. Disease and Therapeutic Context`}
          description="Condition terms and therapeutic statements taken from the retrieved records. A broad disease query is not treated as one homogeneous condition."
          isEmpty={!d?.therapeutic_evidence && conditions.length === 0}
          emptyMessage="Neither the retrieved trials nor the synthesis carried disease context for this query."
        >
          {d?.therapeutic_evidence && (
            <div className="mb-4">
              <BulletList text={d.therapeutic_evidence} />
            </div>
          )}
          {conditions.length > 0 && (
            <div className="rounded-md border border-slate-200 bg-slate-50 px-4 py-3">
              <p className="text-[11px] font-semibold uppercase tracking-wider text-slate-500">
                Condition terms reported by the retrieved trials
              </p>
              <ul className="mt-2 flex flex-wrap gap-1.5">
                {conditions.map((c) => (
                  <li
                    key={c}
                    className="rounded border border-slate-200 bg-white px-2 py-0.5 text-[11px] text-slate-600"
                  >
                    {c}
                  </li>
                ))}
              </ul>
              <p className="mt-2 text-[11px] leading-relaxed text-slate-500">
                These are the registry&apos;s own condition strings for the retrieved
                studies, not a disease hierarchy. The query was applied as submitted, so
                no subtype filtering was performed for this dossier.
              </p>
            </div>
          )}
        </DossierSection>
      ),
    });
  }

  if (signals.compound && d?.compound_profile) {
    const n = parts.length + 1;
    parts.push({
      id: "compound",
      label: `${n} Compound`,
      node: (
        <DossierSection title={`${n}. Compound Profile`}>
          <CompoundCard compound={d.compound_profile} />
        </DossierSection>
      ),
    });
  }

  if (signals.targets) {
    const n = parts.length + 1;
    parts.push({
      id: "mechanism",
      label: `${n} Mechanism`,
      node: (
        <DossierSection
          title={`${n}. Mechanism and Target Biology`}
          description="Target statements from UniProt and the retrieved literature."
          isEmpty={!d?.mechanism && targetItems.length === 0}
          emptyMessage="UniProt returned no target record for this query and the synthesis reported no mechanism, so nothing is asserted here."
        >
          {d?.mechanism && (
            <div className="mb-4">
              <BulletList text={d.mechanism} />
            </div>
          )}
          {targetItems.length > 0 && <TargetTable targets={targetItems} />}
        </DossierSection>
      ),
    });
  }

  const nLit = parts.length + 1;
  parts.push({
    id: "literature",
    label: `${nLit} Literature`,
    node: (
      <DossierSection
        title={`${nLit}. Literature Evidence`}
        description="Evidence classes are assigned from source record metadata, with the criteria listed beside each class. Publication type is not a quality score, and no numeric evidence score is computed."
        note={subtypeScope}
        isEmpty={
          !d?.literature_summary &&
          literatureItems.length === 0 &&
          !data.evidence_strength
        }
        emptyMessage="No publication records were retrieved from PubMed or Europe PMC for this query, so no evidence distribution can be shown."
      >
        {d?.literature_summary && (
          <div className="mb-4">
            <BulletList text={d.literature_summary} />
          </div>
        )}
        {data.evidence_strength && (
          <div className="mb-5">
            <EvidenceStrengthPanel strength={data.evidence_strength} />
          </div>
        )}
        <LiteratureTable
          items={literatureItems}
          query={data.query}
          targetTerms={targetItems
            .map((t) => t.gene ?? t.name)
            .filter((name): name is string => Boolean(name))}
        />
      </DossierSection>
    ),
  });

  const nTrials = parts.length + 1;
  parts.push({
    id: "trials",
    label: `${nTrials} Clinical development`,
    node: (
      <DossierSection
        title={`${nTrials}. Clinical Development`}
        description="Counts, charts and the record list below are computed from the same deduplicated ClinicalTrials.gov records. Phase and status are separate dimensions, and no model estimates these numbers. This is the only section that reports trial counts."
        isEmpty={trialItems.length === 0 && !analytics}
        emptyMessage="No trial records were retrieved for this query. That describes the retrieved set, not whether a trial exists."
        note={subtypeScope || undefined}
      >
        {d?.clinical_development && (
          <div className="mb-4">
            <BulletList text={d.clinical_development} />
          </div>
        )}
        <ClinicalTrialDashboard
          trials={trialItems}
          analytics={analytics}
          candidateAnalytics={data.candidate_analytics}
          metadata={analytics?.metadata ?? null}
        />
      </DossierSection>
    ),
  });

  if (d?.safety || regulatoryItems.length > 0) {
    const n = parts.length + 1;
    parts.push({
      id: "safety",
      label: `${n} Safety`,
      node: (
        <DossierSection
          title={`${n}. Safety and Regulatory Intelligence`}
          description="Label passages quoted from openFDA with their source links. Equivalent passages are consolidated; distinct formulations and label versions stay separate."
        >
          {d?.safety && (
            <div className="mb-4">
              <BulletList text={d.safety} />
            </div>
          )}
          <RegulatoryTable items={regulatoryItems} />
        </DossierSection>
      ),
    });
  }

  const nOpp = parts.length + 1;
  parts.push({
    id: "opportunities",
    label: `${nOpp} Opportunities`,
    node: (
      <DossierSection
        title={`${nOpp}. Potential Research Opportunities`}
        description="Conflicts and open questions suggested by the retrieved evidence. An empty part of this section means the comparison was skipped or found nothing in these records — never that the wider literature agrees."
        isEmpty={
          gaps.length === 0 &&
          !d?.contradictory_findings &&
          !d?.research_opportunities
        }
        emptyMessage="AI synthesis was unavailable, so no contradiction comparison, gap analysis or hypothesis generation was performed for this dossier."
      >
        <div className="space-y-5">
          {d?.contradictory_findings && (
            <ContradictoryFindingsPanel
              findings={d.contradictory_findings}
              aiSynthesized={data.ai_synthesized}
            />
          )}
          <ResearchGapPanel gaps={gaps} aiSynthesized={data.ai_synthesized} />
          {d?.research_opportunities && (
            <>
              <div className="flex items-start gap-2 rounded-md border border-amber-200 bg-amber-50 px-3 py-2">
                <span className="mt-0.5 text-amber-500" aria-hidden="true">
                  ⚠
                </span>
                <p className="text-xs font-medium text-amber-800">
                  AI-generated hypotheses — not established science. Verify
                  independently before acting on them.
                </p>
              </div>
              <BulletList text={d.research_opportunities} />
            </>
          )}
        </div>
      </DossierSection>
    ),
  });

  const nSrc = parts.length + 1;
  parts.push({
    id: "sources",
    label: `${nSrc} Sources`,
    node: (
      <DossierSection
        title={`${nSrc}. Sources, Retrieval Metadata and Limitations`}
        description="What was retrieved, when, from where, and what this dossier does not cover."
      >
        <div className="space-y-5">
          <SourceStatusPanel
            sources={data.sources}
            retrievedAt={data.retrieved_at}
            registryRetrievedAt={analytics?.metadata.retrieved_at ?? null}
          />
          {d?.evidence_gaps && (
            <div>
              <p className="mb-2 text-xs font-semibold uppercase tracking-widest text-slate-400">
                Retrieval limitations
              </p>
              <BulletList text={d.evidence_gaps} />
            </div>
          )}
          {d?.references && d.references.length > 0 && (
            <div>
              <p className="mb-2 text-xs font-semibold uppercase tracking-widest text-slate-400">
                References
              </p>
              <ol className="space-y-2">
                {d.references.map((ref, i) => (
                  <li key={i} className="flex gap-2 text-xs text-slate-600">
                    <span className="shrink-0 font-medium text-slate-400">
                      [{i + 1}]
                    </span>
                    <span className="flex flex-wrap gap-1">
                      <span>{ref}</span>
                      <ReferenceCitation reference={ref} index={i} />
                    </span>
                  </li>
                ))}
              </ol>
            </div>
          )}
        </div>
      </DossierSection>
    ),
  });

  return (
    <div className="flex flex-col gap-5">
      <DrugHeader
        query={data.query}
        compoundName={d?.compound_profile?.name}
        status={data.status}
        mode={data.search_mode ?? mode}
      />

      <StatusBanner data={data} onRetry={load} retrying={loading} />

      <ExportControls data={data} query={query} />

      <SectionNav ids={parts.map(({ id, label }) => ({ id, label }))} />

      {parts.map((part) => (
        <div key={part.id} id={part.id} className="scroll-mt-16">
          {part.node}
        </div>
      ))}
    </div>
  );
}

// ─── Page wrapper (suspense for useSearchParams) ──────────────────────────────

function DossierPageInner() {
  const params = useSearchParams();
  const query = params.get("query") ?? "";
  // A URL without a mode is a compound search, which is how every existing link
  // and bookmark reaches a dossier.
  const rawMode = params.get("mode");
  const mode: SearchMode =
    rawMode === "disease" || rawMode === "target" || rawMode === "compound"
      ? rawMode
      : "compound";

  if (!query) {
    return (
      <div className="flex flex-col items-center justify-center py-24 text-center">
        <p className="mb-4 text-sm text-slate-500">No query provided.</p>
        <Link
          href="/"
          className="text-sm font-medium text-indigo-600 hover:underline"
        >
          ← Go to search
        </Link>
      </div>
    );
  }

  return <DossierContent query={query} mode={mode} />;
}

export default function DossierPage() {
  return (
    // Wide enough for the charts and the trial table columns.
    <div className="mx-auto max-w-6xl px-4 py-8 sm:px-6 lg:px-8">
      <Suspense fallback={<LoadingState message="Loading..." />}>
        <DossierPageInner />
      </Suspense>
    </div>
  );
}
