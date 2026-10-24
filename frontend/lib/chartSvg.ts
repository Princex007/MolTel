/**
 * Renders a ChartSpec to a self-contained SVG string.
 *
 * Exports need figures that survive being opened offline, so charts are drawn
 * from the same spec the dashboard uses rather than scraped from the live DOM.
 * Every style is an attribute — no external CSS, nothing for a rasteriser to
 * lose.
 */

import type { ChartSpec } from "./trialCharts";

const WIDTH = 760;
const BAR_H = 22;
const BAR_GAP = 10;
const LEFT_GUTTER = 190;
const RIGHT_GUTTER = 60;

function esc(value: string): string {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

/** Greedy word wrap sized for the given font so long titles never clip. */
function wrap(text: string, maxChars: number): string[] {
  const words = String(text).split(/\s+/).filter(Boolean);
  const lines: string[] = [];
  let line = "";
  for (const w of words) {
    if (!line.length) line = w;
    else if (line.length + 1 + w.length <= maxChars) line += " " + w;
    else {
      lines.push(line);
      line = w;
    }
  }
  if (line) lines.push(line);
  return lines.length ? lines : [""];
}

function trunc(text: string, max: number): string {
  const t = String(text).trim();
  return t.length > max ? `${t.slice(0, max - 1)}…` : t;
}

export interface RenderedChart {
  svg: string;
  width: number;
  height: number;
}

export function renderChartSvg(chart: ChartSpec): RenderedChart {
  const titleLines = wrap(chart.title, 78);
  const subtitleLines = wrap(chart.subtitle, 108).slice(0, 4);
  const headerH = 14 + titleLines.length * 18 + subtitleLines.length * 14 + 12;

  const hasData = chart.data.length > 0;
  const plotH = hasData
    ? chart.kind === "bar"
      ? chart.data.length * (BAR_H + BAR_GAP) + 8
      : 170
    : 60;
  const footerH = 40;
  const height = headerH + plotH + footerH;

  const max = Math.max(1, ...chart.data.map((d) => d.value));
  const parts: string[] = [];

  parts.push(
    `<svg xmlns="http://www.w3.org/2000/svg" width="${WIDTH}" height="${height}" viewBox="0 0 ${WIDTH} ${height}" role="img" aria-label="${esc(
      chart.title
    )}">`
  );
  parts.push(`<rect width="${WIDTH}" height="${height}" fill="#ffffff"/>`);
  parts.push(
    `<text x="16" y="24" font-family="Helvetica, Arial, sans-serif" font-size="15" font-weight="bold" fill="#0f172a">${esc(
      chart.title
    )}</text>`
  );
  subtitleLines.forEach((line, i) => {
    parts.push(
      `<text x="16" y="${44 + i * 14}" font-family="Helvetica, Arial, sans-serif" font-size="10.5" fill="#64748b">${esc(
        line
      )}</text>`
    );
  });

  const top = headerH;

  if (!hasData) {
    parts.push(
      `<text x="16" y="${top + 30}" font-family="Helvetica, Arial, sans-serif" font-size="12" fill="#94a3b8">${esc(
        chart.emptyNote ?? "No data."
      )}</text>`
    );
  } else if (chart.kind === "bar") {
    chart.data.forEach((d, i) => {
      const y = top + i * (BAR_H + BAR_GAP);
      const w = Math.max(2, Math.round(((WIDTH - LEFT_GUTTER - RIGHT_GUTTER) * d.value) / max));
      parts.push(
        `<text x="${LEFT_GUTTER - 8}" y="${y + BAR_H - 7}" text-anchor="end" font-family="Helvetica, Arial, sans-serif" font-size="11" fill="#334155">${esc(
          trunc(d.label, 30)
        )}</text>`
      );
      parts.push(
        `<rect x="${LEFT_GUTTER}" y="${y}" width="${w}" height="${BAR_H}" rx="3" fill="${d.color}"/>`
      );
      parts.push(
        `<text x="${LEFT_GUTTER + w + 6}" y="${y + BAR_H - 7}" font-family="Helvetica, Arial, sans-serif" font-size="11" font-weight="bold" fill="#0f172a">${
          d.value
        }</text>`
      );
    });
  } else {
    const baseY = top + plotH - 34;
    const plotW = WIDTH - 32 - 16;
    const slot = plotW / Math.max(1, chart.data.length);
    const barW = Math.max(6, Math.min(46, slot - 8));
    const axisH = plotH - 60;
    parts.push(
      `<line x1="16" y1="${baseY}" x2="${WIDTH - 16}" y2="${baseY}" stroke="#cbd5e1" stroke-width="1"/>`
    );
    chart.data.forEach((d, i) => {
      const h = Math.max(2, Math.round((axisH * d.value) / max));
      const x = 20 + i * slot + (slot - barW) / 2;
      const y = baseY - h;
      parts.push(
        `<rect x="${x.toFixed(1)}" y="${y}" width="${barW.toFixed(1)}" height="${h}" rx="2" fill="${d.color}"/>`
      );
      parts.push(
        `<text x="${(x + barW / 2).toFixed(1)}" y="${y - 4}" text-anchor="middle" font-family="Helvetica, Arial, sans-serif" font-size="9" fill="#334155">${
          d.value
        }</text>`
      );
      // Stagger labels two rows deep instead of rotating them.
      const label = trunc(d.label, 10);
      const labelY = baseY + 14 + (i % 2) * 11;
      parts.push(
        `<text x="${(x + barW / 2).toFixed(1)}" y="${labelY}" text-anchor="middle" font-family="Helvetica, Arial, sans-serif" font-size="9" fill="#475569">${esc(
          label
        )}</text>`
      );
    });
  }

  parts.push(
    `<text x="16" y="${height - 12}" font-family="Helvetica, Arial, sans-serif" font-size="10" fill="#64748b">Counts ${esc(
      chart.unit
    )}.</text>`
  );
  parts.push("</svg>");
  return { svg: parts.join(""), width: WIDTH, height };
}
