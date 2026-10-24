/**
 * Printable HTML report. This is the only path allowed to reach the browser
 * print dialog — downloads never touch it.
 *
 * Charts are embedded as inline vector SVG, so a printed or saved-as-PDF copy
 * shows the same figures as the dashboard.
 */

import { renderChartSvg } from "../chartSvg";
import type { ChartSpec } from "../trialCharts";
import {
  PRODUCT_NAME,
  type ReportModel,
  type ReportSection,
  type ReportTable,
} from "../report";

function esc(value: unknown): string {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function linkify(text: string): string {
  const t = text.trim();
  return /^https?:\/\/\S+$/.test(t)
    ? `<a href="${esc(t)}">${esc(t.replace(/^https?:\/\//, "").slice(0, 70))}</a>`
    : esc(text);
}

function tableHtml(table: ReportTable): string {
  const head = table.columns.map((c) => `<th>${esc(c)}</th>`).join("");
  const body = table.rows
    .map(
      (row) =>
        `<tr>${row
          .map((cell) => `<td>${linkify(String(cell ?? ""))}</td>`)
          .join("")}</tr>`
    )
    .join("");
  const notes = [table.note, table.omittedRows ? `${table.omittedRows} further row(s) omitted here; complete set in the CSV export.` : ""]
    .filter(Boolean)
    .join(" ");
  return `<table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>${
    notes ? `<p class="note">${esc(notes)}</p>` : ""
  }`;
}

function chartHtml(chart: ChartSpec): string {
  return `<figure>${renderChartSvg(chart).svg}<figcaption>${esc(chart.title)} — ${esc(
    chart.subtitle
  )} Counts ${esc(chart.unit)}.</figcaption></figure>`;
}

function sectionHtml(section: ReportSection): string {
  const parts: string[] = [
    `<h2>${section.number}. ${esc(section.title)}</h2>`,
    section.description ? `<p class="lede">${esc(section.description)}</p>` : "",
  ];
  for (const node of section.nodes) {
    switch (node.kind) {
      case "prose":
        parts.push(`<p>${esc(node.text)}</p>`);
        break;
      case "bullets":
        parts.push(`<ul>${node.items.map((i) => `<li>${esc(i)}</li>`).join("")}</ul>`);
        break;
      case "callout":
        parts.push(
          `<div class="callout ${node.tone}"><strong>${esc(node.title)}</strong><p>${esc(
            node.text
          )}</p></div>`
        );
        break;
      case "kv":
        parts.push(
          `<table class="kv"><tbody>${node.entries
            .map(([k, v]) => `<tr><th>${esc(k)}</th><td>${linkify(v)}</td></tr>`)
            .join("")}</tbody></table>`
        );
        break;
      case "table":
        parts.push(tableHtml(node.table));
        break;
      case "charts":
        parts.push(node.charts.map(chartHtml).join(""));
        break;
      case "references":
        parts.push(
          `<h3>References</h3><ol>${node.items
            .map((r) => `<li>${linkify(r)}</li>`)
            .join("")}</ol>`
        );
        break;
    }
  }
  return `<section>${parts.join("")}</section>`;
}

const STYLES = `
:root { color-scheme: light; }
* { box-sizing: border-box; }
body { font: 11pt/1.5 "Segoe UI", Helvetica, Arial, sans-serif; color: #1e293b; margin: 0; }
.masthead { background: #4f46e5; color: #fff; padding: 20px 24px; }
.masthead h1 { margin: 0; font-size: 13pt; letter-spacing: .18em; }
.masthead p { margin: 4px 0 0; font-size: 10pt; opacity: .9; }
main { padding: 18px 24px 40px; }
h2 { font-size: 13pt; margin: 22px 0 4px; border-bottom: 1px solid #e2e8f0; padding-bottom: 4px; }
h3 { font-size: 11pt; margin: 16px 0 4px; }
.lede { color: #64748b; font-size: 9.5pt; margin: 0 0 8px; }
p, li { font-size: 10.5pt; }
ul { margin: 6px 0 10px 18px; }
table { width: 100%; border-collapse: collapse; margin: 10px 0 4px; font-size: 8.5pt; table-layout: fixed; }
th, td { border: 1px solid #e2e8f0; padding: 4px 6px; text-align: left; vertical-align: top; word-wrap: break-word; overflow-wrap: anywhere; }
td { white-space: pre-line; }
thead { display: table-header-group; }
thead th { background: #eef2ff; }
tr { break-inside: avoid; page-break-inside: avoid; }
table.kv th { width: 30%; background: #f8fafc; }
.note { color: #64748b; font-size: 8pt; font-style: italic; margin: 2px 0 12px; }
.callout { border-left: 3px solid #f59e0b; background: #fffbeb; padding: 8px 12px; margin: 10px 0; break-inside: avoid; }
.callout.info { border-color: #94a3b8; background: #f8fafc; }
.callout.danger { border-color: #dc2626; background: #fef2f2; }
.callout strong { display: block; font-size: 10pt; margin-bottom: 3px; }
.callout p { margin: 0; font-size: 9.5pt; }
figure { margin: 14px 0; break-inside: avoid; page-break-inside: avoid; }
figure svg { width: 100%; height: auto; }
figcaption { font-size: 8.5pt; color: #64748b; font-style: italic; margin-top: 3px; }
a { color: #1d4ed8; text-decoration: none; }
section { break-inside: auto; }
@page { size: A4; margin: 16mm 14mm; }
@media print { .masthead { -webkit-print-color-adjust: exact; print-color-adjust: exact; } }
`;

export function buildPrintDocument(model: ReportModel): string {
  const body = model.sections.map(sectionHtml).join("");
  return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<title>${esc(model.product)} — ${esc(model.query)}</title>
<meta name="generator" content="${esc(model.product)}" />
<meta name="description" content="Research dossier generated from public scientific databases." />
${`<style>${STYLES}</style>`}
</head>
<body>
<header class="masthead">
  <h1>${esc(model.product.toUpperCase())}</h1>
  <p>${esc(model.title)}</p>
  <p>Query &ldquo;${esc(model.query)}&rdquo; | ${esc(model.statusLabel)} retrieval | generated ${esc(
    new Date().toLocaleString()
  )}</p>
</header>
<main>
<p class="lede">Every figure is computed from records retrieved from public scientific databases. AI-written interpretation, where present, is labelled. Not for clinical use.</p>
${body}
</main>
</body>
</html>`;
}

/**
 * Send the report to the browser's print workflow in an isolated frame, so the
 * dossier page itself is never replaced or left mid-print.
 */
export function printReport(model: ReportModel): void {
  const html = buildPrintDocument(model);
  const frame = document.createElement("iframe");
  frame.style.position = "fixed";
  frame.style.right = "0";
  frame.style.bottom = "0";
  frame.style.width = "0";
  frame.style.height = "0";
  frame.setAttribute("aria-hidden", "true");
  frame.setAttribute("title", `${PRODUCT_NAME} print preview`);
  document.body.appendChild(frame);

  const win = frame.contentWindow;
  const doc = win?.document;
  if (!win || !doc) {
    frame.remove();
    throw new Error("This browser blocked the print frame. Use Download PDF instead.");
  }
  doc.open();
  doc.write(html);
  doc.close();

  const cleanup = () => frame.remove();
  win.addEventListener("afterprint", cleanup, { once: true });
  // Some engines fire print only after the frame has laid out.
  win.setTimeout(() => {
    win.focus();
    win.print();
    setTimeout(cleanup, 60000);
  }, 250);
}
