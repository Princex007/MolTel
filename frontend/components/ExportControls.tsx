"use client";

import { useState } from "react";
import type { DossierResponse } from "@/lib/api";
import { buildReportModel, reportFileName, type ReportModel } from "@/lib/report";
import { rasterizeCharts, type RasterImage } from "@/lib/rasterize";
import { buildCsv, csvFileName, datasetOptions, type Dataset } from "@/lib/export/csv";
import { downloadBlob } from "@/lib/download";

type Action = "pdf" | "docx" | "csv" | "print";

interface Props {
  data: DossierResponse;
  query: string;
}

const BUTTON =
  "rounded-md border border-slate-300 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 shadow-sm transition-colors hover:border-indigo-400 hover:text-indigo-700 disabled:cursor-not-allowed disabled:opacity-50";

export default function ExportControls({ data, query }: Props) {
  const [busy, setBusy] = useState<Action | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [lastAction, setLastAction] = useState<Action | null>(null);
  const [dataset, setDataset] = useState<Dataset>("trials");
  const [saved, setSaved] = useState<string | null>(null);

  async function prepareImages(
    model: ReportModel
  ): Promise<Map<string, RasterImage>> {
    // Charts are drawn from the same specs the dashboard used and rasterised
    // into the file, so the document shows them offline.
    const images = await rasterizeCharts(model.charts, 2);
    if (model.charts.length > 0 && images.size === 0) {
      throw new Error(
        "Charts could not be rendered to images in this browser, so they would be missing from the file. Use Print for a vector copy."
      );
    }
    return images;
  }

  async function run(action: Action) {
    setBusy(action);
    setLastAction(action);
    setError(null);
    setSaved(null);
    try {
      const model = buildReportModel(data, query);
      if (action === "csv") {
        downloadBlob(
          new Blob([buildCsv(data, query, dataset)], {
            type: "text/csv;charset=utf-8",
          }),
          csvFileName(query, dataset)
        );
        setSaved(csvFileName(query, dataset));
        return;
      }
      if (action === "print") {
        const { printReport } = await import("@/lib/export/print");
        printReport(model);
        return;
      }
      const images = await prepareImages(model);
      if (action === "pdf") {
        // Loaded on demand: jsPDF and docx are the heavy part of this page.
        const { buildPdf } = await import("@/lib/export/pdf");
        const name = reportFileName(query, "pdf");
        downloadBlob(await buildPdf(model, images), name);
        setSaved(name);
        return;
      }
      const { buildDocx } = await import("@/lib/export/docx");
      const name = reportFileName(query, "docx");
      downloadBlob(await buildDocx(model, images), name);
      setSaved(name);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "The export failed for an unknown reason."
      );
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="rounded-lg border border-slate-200 bg-white px-4 py-3 shadow-sm">
      <div className="flex flex-wrap items-center gap-2">
        <span className="mr-1 text-[11px] font-semibold uppercase tracking-widest text-slate-400">
          Export
        </span>
        <button
          type="button"
          className={BUTTON}
          onClick={() => run("pdf")}
          disabled={busy !== null}
        >
          {busy === "pdf" ? "Generating PDF…" : "Download PDF"}
        </button>
        <button
          type="button"
          className={BUTTON}
          onClick={() => run("docx")}
          disabled={busy !== null}
        >
          {busy === "docx" ? "Generating Word…" : "Download Word (.docx)"}
        </button>

        <label className="flex items-center gap-1.5">
          <span className="sr-only">Data set to export</span>
          <select
            className="rounded-md border border-slate-300 bg-white px-2 py-1.5 text-xs text-slate-700"
            value={dataset}
            onChange={(e) => setDataset(e.target.value as Dataset)}
            disabled={busy !== null}
          >
            {datasetOptions(data).map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </label>
        <button
          type="button"
          className={BUTTON}
          onClick={() => run("csv")}
          disabled={busy !== null}
        >
          {busy === "csv" ? "Preparing CSV…" : "Export Data (CSV)"}
        </button>
        <button
          type="button"
          className={BUTTON}
          onClick={() => run("print")}
          disabled={busy !== null}
        >
          {busy === "print" ? "Opening print…" : "Print"}
        </button>
      </div>

      <p className="mt-2 text-[11px] leading-relaxed text-slate-500">
        PDF and Word download files directly and embed the trial charts as
        high-resolution figures. Print is the only action that opens your
        browser&apos;s print workflow. Charts, tables and record counts come from
        the same data this page displays.
      </p>

      {saved && (
        <p className="mt-2 text-[11px] font-medium text-green-700">
          Saved {saved}.
        </p>
      )}

      {error && (
        <div className="mt-2 flex flex-wrap items-center gap-2 rounded-md border border-red-200 bg-red-50 px-3 py-2">
          <p className="text-[11px] font-medium text-red-800">{error}</p>
          {lastAction && (
            <button
              type="button"
              className="rounded border border-red-300 bg-white px-2 py-0.5 text-[11px] font-medium text-red-700 hover:bg-red-100"
              onClick={() => run(lastAction)}
            >
              Try again
            </button>
          )}
        </div>
      )}
    </div>
  );
}
