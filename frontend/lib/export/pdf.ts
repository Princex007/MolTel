/**
 * PDF dossier generation with jsPDF.
 *
 * Produces a real .pdf file: selectable text, hyperlinked sources, embedded
 * high-resolution chart images, repeating table headers and page footers. The
 * figures are rasterised into the document, so the file displays offline.
 */

import { jsPDF } from "jspdf";
import type { ChartSpec } from "../trialCharts";
import type { RasterImage } from "../rasterize";
import type { ReportModel, ReportSection, ReportTable } from "../report";
import { PRODUCT_NAME } from "../report";

const PAGE_W = 595.28;
const PAGE_H = 841.89;
const MARGIN_X = 46;
const MARGIN_TOP = 52;
const MARGIN_BOTTOM = 58;
const CONTENT_W = PAGE_W - MARGIN_X * 2;

/** jsPDF's built-in fonts cover WinAnsi; map the frequent extras to ASCII. */
const UNICODE_FALLBACKS: Record<string, string> = {
  "—": "-",
  "–": "-",
  "‘": "'",
  "’": "'",
  "“": '"',
  "”": '"',
  "…": "...",
  "α": "alpha",
  "β": "beta",
  "γ": "gamma",
  "δ": "delta",
  "μ": "u",
  "λ": "lambda",
  "κ": "kappa",
  "θ": "theta",
  "φ": "phi",
  "ψ": "psi",
  "Ω": "Omega",
  "ω": "omega",
  "Δ": "delta",
  "°": " deg",
  "±": "+/-",
  "×": "x",
  "→": "->",
  "←": "<-",
  "≈": "~",
  "≤": "<=",
  "≥": ">=",
  "•": "*",
  "✓": "v",
  "✗": "x",
};

export function toWinAnsi(value: string): string {
  let out = String(value ?? "");
  for (const [ch, rep] of Object.entries(UNICODE_FALLBACKS)) {
    if (out.includes(ch)) out = out.split(ch).join(rep);
  }
  return out
    .replace(/[·∙]/g, "-")
    // eslint-disable-next-line no-control-regex
    .replace(/[^\x09\x0a\x0d\x20-\xff]/g, "");
}

function isUrl(text: string): boolean {
  return /^https?:\/\/\S+$/.test(text.trim());
}

/** Splitting mirrors jsPDF's own wrapping so a column can hold its longest token. */
function tokens(text: string): string[] {
  return String(text ?? "")
    .split(/[\s,;|/]+/)
    .filter(Boolean);
}

const COLUMN_HINTS: Record<string, number> = {
  title: 3.2,
  statement: 3.0,
  function: 2.6,
  name: 1.5,
  explanation: 2.2,
  "current evidence": 2,
  uncertainty: 2,
  "suggested next step": 2,
  claim: 2,
  "claim in tension": 2,
  "study a": 1.6,
  "study b": 1.6,
  detail: 1.8,
  synonyms: 1.6,
  "condition terms reported by the retrieved trials": 3,
  year: 0.6,
  count: 0.7,
  records: 0.8,
  status: 1.4,
  "registry status": 1.4,
  phase: 1.55,
  "nct id": 1.45,
  start: 1.25,
  completion: 1.25,
  sponsor: 1.7,
  source: 1.2,
  // URL cells are drawn as a short "source" link, so they need little width.
  link: 0.9,
  url: 0.9,
};

function columnWeights(columns: string[], rows: string[][]): number[] {
  return columns.map((col, i) => {
    const key = col.toLowerCase();
    if (COLUMN_HINTS[key]) return COLUMN_HINTS[key];
    const sample = Math.max(
      col.length,
      ...rows.slice(0, 12).map((r) => Math.min(String(r[i] ?? "").length, 60))
    );
    return Math.max(0.6, sample / 24);
  });
}

class Layout {
  private doc: jsPDF;
  y: number;
  private bottom: number;

  constructor(doc: jsPDF) {
    this.doc = doc;
    this.y = MARGIN_TOP;
    this.bottom = PAGE_H - MARGIN_BOTTOM;
  }

  get page(): jsPDF {
    return this.doc;
  }

  space(h: number): void {
    if (this.y + h > this.bottom) this.newPage();
  }

  newPage(): void {
    this.doc.addPage();
    this.y = MARGIN_TOP;
  }

  at(): number {
    return this.y;
  }

  set(value: number): void {
    this.y = value;
  }

  heading(text: string, size: number, gapBefore = 0): void {
    this.space(size + gapBefore + 10);
    this.y += gapBefore;
    this.doc.setFont("helvetica", "bold");
    this.doc.setFontSize(size);
    this.doc.setTextColor(15, 23, 42);
    this.doc.text(toWinAnsi(text), MARGIN_X, this.y + size);
    this.y += size + 8;
  }

  paragraph(text: string, opts: { size?: number; color?: [number, number, number]; indent?: number; style?: "normal" | "bold" | "italic" } = {}): void {
    const size = opts.size ?? 9.5;
    const indent = opts.indent ?? 0;
    const style = opts.style ?? "normal";
    const color = opts.color ?? [51, 65, 85];
    const lines = this.doc.splitTextToSize(toWinAnsi(text), CONTENT_W - indent) as string[];
    for (const line of lines) {
      this.space(size * 1.45);
      this.doc.setFont("helvetica", style);
      this.doc.setFontSize(size);
      this.doc.setTextColor(...color);
      this.doc.text(line, MARGIN_X + indent, this.y + size);
      this.y += size * 1.45;
    }
  }

  bullets(items: string[]): void {
    for (const item of items) {
      const size = 9.5;
      const lines = this.doc.splitTextToSize(toWinAnsi(item), CONTENT_W - 16) as string[];
      lines.forEach((line, i) => {
        this.space(size * 1.45);
        this.doc.setFont("helvetica", "normal");
        this.doc.setFontSize(size);
        if (i === 0) {
          this.doc.setTextColor(79, 70, 229);
          this.doc.text("-", MARGIN_X + 4, this.y + size);
        }
        this.doc.setTextColor(51, 65, 85);
        this.doc.text(line, MARGIN_X + 16, this.y + size);
        this.y += size * 1.45;
      });
    }
  }

  callout(tone: string, title: string, text: string): void {
    const fill: [number, number, number] =
      tone === "danger" ? [254, 242, 242] : tone === "info" ? [241, 245, 249] : [255, 251, 235];
    const line: [number, number, number] =
      tone === "danger" ? [248, 180, 180] : tone === "info" ? [203, 213, 225] : [240, 200, 120];
    const inner = CONTENT_W - 20;
    const titleLines = this.doc.splitTextToSize(toWinAnsi(title), inner) as string[];
    const bodyLines = this.doc.splitTextToSize(toWinAnsi(text), inner) as string[];
    const h = 18 + titleLines.length * 13 + bodyLines.length * 13 + 8;
    this.space(h + 10);
    const top = this.y;
    this.doc.setFillColor(...fill);
    this.doc.setDrawColor(...line);
    this.doc.roundedRect(MARGIN_X, top, CONTENT_W, h, 3, 3, "FD");
    this.doc.setFont("helvetica", "bold");
    this.doc.setFontSize(9.5);
    this.doc.setTextColor(120, 80, 20);
    let cursor = top + 15;
    titleLines.forEach((l) => {
      this.doc.text(l, MARGIN_X + 10, cursor);
      cursor += 13;
    });
    this.doc.setFont("helvetica", "normal");
    this.doc.setTextColor(60, 55, 45);
    bodyLines.forEach((l) => {
      this.doc.text(l, MARGIN_X + 10, cursor);
      cursor += 13;
    });
    this.y = top + h + 10;
  }

  kv(entries: [string, string][]): void {
    for (const [label, value] of entries) {
      const size = 9;
      const labelLines = this.doc.splitTextToSize(toWinAnsi(label), 150) as string[];
      const valueLines = this.doc.splitTextToSize(toWinAnsi(value), CONTENT_W - 160) as string[];
      const rows = Math.max(labelLines.length, valueLines.length);
      this.space(rows * 12 + 4);
      const top = this.y;
      this.doc.setFont("helvetica", "bold");
      this.doc.setFontSize(size);
      this.doc.setTextColor(71, 85, 105);
      labelLines.forEach((l, i) => this.doc.text(l, MARGIN_X, top + size + i * 12));
      this.doc.setFont("helvetica", "normal");
      this.doc.setTextColor(51, 65, 85);
      valueLines.forEach((l, i) => this.doc.text(l, MARGIN_X + 160, top + size + i * 12));
      this.y = top + rows * 12 + 4;
    }
  }

  /** Widest unbreakable token in a string, at the font currently selected. */
  private maxTokenWidth(text: string): number {
    let widest = 0;
    for (const token of tokens(text)) widest = Math.max(widest, this.doc.getTextWidth(token));
    return widest;
  }

  /**
   * Narrowest width, at the given fonts, that keeps every value whole.
   * `wholeLines` additionally keeps a labelled line such as
   * "last update 2026-10-15" on one row, so its value is not pushed out of the
   * cell; turning it off lets long lines wrap at a space instead.
   */
  private requiredWidths(
    table: ReportTable,
    bodyFont: number,
    headFont: number,
    wholeLines: boolean
  ): number[] {
    // The header is drawn at headFont, which is never smaller than the body.
    this.doc.setFont("helvetica", "bold");
    this.doc.setFontSize(headFont);
    const required = table.columns.map((col) => {
      const text = toWinAnsi(col);
      // A column that only holds the header's widest word prints the caption on
      // four lines and drops two of them, which mislabels the column. Half the
      // unbroken line is enough for a caption to sit on two.
      const halved = this.doc.getTextWidth(text) / 2 + 5;
      return Math.max(this.maxTokenWidth(text), halved) + 9;
    });

    this.doc.setFont("helvetica", "normal");
    this.doc.setFontSize(bodyFont);
    table.rows.slice(0, 40).forEach((row) => {
      row.forEach((cell, i) => {
        if (i >= required.length) return;
        // A single URL is drawn as a short "source" link, so its length is
        // irrelevant; several in one cell are not, so they are measured.
        const raw = String(cell ?? "").trim();
        if (isUrl(raw)) {
          required[i] = Math.max(required[i], this.doc.getTextWidth("source") + 12);
          return;
        }
        const text = toWinAnsi(raw);
        let need = this.maxTokenWidth(text);
        if (wholeLines && text.includes("\n")) {
          // Only a composite cell gets its lines kept whole: a one-line value
          // such as "No matched openFDA label" wraps at a space instead, which
          // costs the table far less width than demanding the whole phrase.
          for (const line of text.split("\n")) {
            const width = this.doc.getTextWidth(line.trim());
            if (width <= CONTENT_W * 0.26 - 9) need = Math.max(need, width);
          }
        }
        required[i] = Math.max(required[i], need + 9);
      });
    });
    return required.map((w) => Math.min(w, CONTENT_W * 0.26));
  }

  /**
   * Column widths that hold every unbreakable value — an NCT ID or an ISO date
   * must not be split mid-token — with the spare space shared by weight.
   * Returns null when the table cannot fit at this font.
   */
  private columnWidths(
    table: ReportTable,
    weights: number[],
    bodyFont: number,
    headFont: number,
    wholeLines: boolean
  ): number[] | null {
    const total = weights.reduce((s, w) => s + w, 0);
    const capped = this.requiredWidths(table, bodyFont, headFont, wholeLines);
    const fixed = capped.reduce((s, w) => s + w, 0);
    if (fixed > CONTENT_W) return null;
    const spare = CONTENT_W - fixed;
    return capped.map((w, i) => w + (spare * weights[i]) / total);
  }

  /**
   * Shrink the type and then relax the line rule before breaking a word. The
   * first attempt that keeps every token whole wins, so an NCT ID, an ISO date
   * and the "source" link are never split; only a table that cannot fit at any
   * size shares the shortfall, where a wrapped word is the lesser fault.
   */
  private fitTable(
    table: ReportTable,
    weights: number[],
    headFont: number
  ): { font: number; cols: number[] } {
    const sizes = [7.5, 7, 6.5, 6];
    const attempts: Array<[number, boolean]> = [
      ...sizes.map((s): [number, boolean] => [s, true]),
      ...sizes.map((s): [number, boolean] => [s, false]),
    ];
    for (const [size, wholeLines] of attempts) {
      const cols = this.columnWidths(table, weights, size, headFont, wholeLines);
      if (cols) return { font: size, cols };
    }
    const font = sizes[sizes.length - 1];
    const capped = this.requiredWidths(table, font, headFont, false);
    const fixed = capped.reduce((s, w) => s + w, 0);
    return { font, cols: capped.map((w) => (CONTENT_W * w) / fixed) };
  }

  table(table: ReportTable): void {
    const weights = columnWeights(table.columns, table.rows);
    const headFont = 7.5;
    const fitted = this.fitTable(table, weights, headFont);
    const bodyFont = fitted.font;
    const cols = fitted.cols;

    const drawHeader = () => {
      this.doc.setFont("helvetica", "bold");
      this.doc.setFontSize(headFont);
      const lines = table.columns.map((col, i) =>
        (this.doc.splitTextToSize(toWinAnsi(col), cols[i] - 9) as string[]).slice(0, 3)
      );
      const rowHeight = headFont + 3;
      const height = 7 + Math.max(1, ...lines.map((l) => l.length)) * rowHeight;
      this.space(height + 4);
      const top = this.y;
      this.doc.setFillColor(241, 245, 249);
      this.doc.setDrawColor(203, 213, 225);
      this.doc.rect(MARGIN_X, top, CONTENT_W, height, "FD");
      this.doc.setTextColor(51, 65, 85);
      let x = MARGIN_X + 4;
      lines.forEach((cell, i) => {
        cell.forEach((line, li) => this.doc.text(line, x, top + headFont + 2 + li * rowHeight));
        x += cols[i];
      });
      this.y = top + height + 2;
    };

    if (table.rows.length === 0) {
      drawHeader();
      this.paragraph("No records in this set.", { size: 8.5, color: [148, 163, 184], indent: 4 });
      return;
    }

    drawHeader();

    // splitTextToSize wraps with whichever font is selected, so select the body
    // font before measuring a single cell — the header is bold and larger, and
    // it is redrawn after every page break.
    for (const row of table.rows) {
      this.doc.setFont("helvetica", "normal");
      this.doc.setFontSize(bodyFont);
      const cellLines = row.map((cell, i) =>
        this.doc.splitTextToSize(toWinAnsi(String(cell ?? "")), cols[i] - 9) as string[]
      );
      // A row taller than this would dominate the page. Anything past the cap
      // says so instead of disappearing.
      const cap = 4;
      const capped = cellLines.map((lines) => {
        if (lines.length <= cap) return lines;
        const shown = lines.slice(0, cap);
        shown[cap - 1] = `${shown[cap - 1]} [...]`;
        return shown;
      });
      const rowH = Math.max(1, ...capped.map((l) => l.length)) * (bodyFont + 3) + 6;
      if (this.y + rowH > this.bottom) {
        this.newPage();
        drawHeader();
      }
      const top = this.y;
      this.doc.setDrawColor(226, 232, 240);
      this.doc.line(MARGIN_X, top + rowH, MARGIN_X + CONTENT_W, top + rowH);
      let x = MARGIN_X + 4;
      capped.forEach((lines, i) => {
        // Detect a URL on the raw cell: wrapping breaks the string up, and a
        // wrapped URL would otherwise be printed as text instead of a link.
        const raw = String(row[i] ?? "").trim();
        if (isUrl(raw)) {
          this.doc.setFont("helvetica", "normal");
          this.doc.setFontSize(bodyFont);
          this.doc.setTextColor(37, 99, 235);
          this.doc.textWithLink("source", x, top + bodyFont + 3, {
            url: raw,
            maxWidth: cols[i] - 8,
          });
        } else {
          this.doc.setFont("helvetica", "normal");
          this.doc.setFontSize(bodyFont);
          this.doc.setTextColor(51, 65, 85);
          lines.forEach((l, li) => this.doc.text(l, x, top + bodyFont + 3 + li * (bodyFont + 3)));
        }
        x += cols[i];
      });
      this.y = top + rowH;
    }

    if (table.note) {
      this.paragraph(table.note, { size: 7.5, color: [100, 116, 139] });
    }
    if (table.omittedRows) {
      this.paragraph(
        `${table.omittedRows} further row(s) are not printed here for legibility; the complete set is in the CSV export.`,
        { size: 7.5, color: [100, 116, 139] }
      );
    }
    this.y += 8;
  }

  chart(chart: ChartSpec, image: RasterImage | undefined): void {
    if (!image) {
      this.paragraph(
        `Figure "${chart.title}" could not be rendered in this environment and is omitted. The underlying records are in the table below and in the CSV export.`,
        { size: 8, color: [180, 60, 60] }
      );
      return;
    }
    const drawW = CONTENT_W;
    const drawH = (image.height / image.width) * drawW;
    // A figure taller than a page loses detail anyway; give it its own page.
    if (this.y + drawH > this.bottom) {
      if (this.y < MARGIN_TOP + 120) this.newPage();
      else this.newPage();
    }
    if (drawH > this.bottom - MARGIN_TOP) {
      const ratio = (this.bottom - MARGIN_TOP - 6) / drawH;
      const h = drawH * ratio;
      this.doc.addImage(image.dataUrl, "PNG", MARGIN_X, this.y, drawW * ratio, h);
      this.y += h + 10;
      return;
    }
    this.doc.addImage(image.dataUrl, "PNG", MARGIN_X, this.y, drawW, drawH);
    this.y += drawH + 10;
  }
}

function renderSection(layout: Layout, section: ReportSection, images: Map<string, RasterImage>): void {
  layout.heading(`${section.number}. ${section.title}`, 13, 14);
  if (section.description) {
    layout.paragraph(section.description, { size: 8.5, color: [100, 116, 139] });
  }
  for (const node of section.nodes) {
    switch (node.kind) {
      case "prose":
        layout.paragraph(node.text);
        break;
      case "bullets":
        layout.bullets(node.items);
        break;
      case "callout":
        layout.callout(node.tone, node.title, node.text);
        break;
      case "kv":
        layout.kv(node.entries);
        layout.y += 6;
        break;
      case "table":
        layout.table(node.table);
        break;
      case "charts":
        for (const chart of node.charts) layout.chart(chart, images.get(chart.id));
        break;
      case "references":
        layout.paragraph("References", { size: 10, style: "bold" });
        layout.bullets(node.items.map((r, i) => `[${i + 1}] ${r}`));
        break;
    }
  }
}

export async function buildPdf(
  model: ReportModel,
  images: Map<string, RasterImage>
): Promise<Blob> {
  const doc = new jsPDF({ unit: "pt", format: "a4", compress: true });
  doc.setProperties({
    title: `${PRODUCT_NAME} — ${model.query}`,
    subject: "Research dossier generated from public scientific databases",
    author: PRODUCT_NAME,
    creator: PRODUCT_NAME,
    keywords: "MolTel, research dossier, clinical trials, literature, sources",
  });

  const layout = new Layout(doc);

  // Masthead
  doc.setFillColor(79, 70, 229);
  doc.rect(0, 0, PAGE_W, 96, "F");
  doc.setFont("helvetica", "bold");
  doc.setFontSize(22);
  doc.setTextColor(255, 255, 255);
  doc.text(PRODUCT_NAME.toUpperCase(), MARGIN_X, 44);
  doc.setFont("helvetica", "normal");
  doc.setFontSize(10);
  doc.setTextColor(226, 232, 255);
  doc.text(toWinAnsi(model.title), MARGIN_X, 64);
  doc.setFontSize(8.5);
  doc.text(
    toWinAnsi(
      `Query: ${model.query}   |   ${model.statusLabel} retrieval   |   generated ${new Date().toLocaleString()}`
    ),
    MARGIN_X,
    80
  );
  layout.set(116);

  layout.paragraph(
    "Every figure in this report is computed from records retrieved from public scientific databases. AI-written interpretation, where present, is labelled. Not for clinical use.",
    { size: 8.5, color: [100, 116, 139] }
  );

  for (const section of model.sections) renderSection(layout, section, images);

  // Footer on every page
  const pages = doc.getNumberOfPages();
  for (let i = 1; i <= pages; i++) {
    doc.setPage(i);
    doc.setFont("helvetica", "normal");
    doc.setFontSize(7.5);
    doc.setTextColor(148, 163, 184);
    doc.line(MARGIN_X, PAGE_H - 42, PAGE_W - MARGIN_X, PAGE_H - 42);
    doc.text(
      toWinAnsi(`${PRODUCT_NAME} — research dossier for "${model.query}"`),
      MARGIN_X,
      PAGE_H - 30
    );
    doc.text(`Page ${i} of ${pages}`, PAGE_W - MARGIN_X, PAGE_H - 30, { align: "right" });
    doc.text(
      "Not for clinical use. Figures reflect the records retrieved at generation time.",
      MARGIN_X,
      PAGE_H - 20
    );
  }

  return doc.output("blob");
}
