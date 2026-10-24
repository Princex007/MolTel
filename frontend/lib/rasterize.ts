/**
 * Turn generated chart SVG into a high-resolution PNG.
 *
 * PDF and Word both embed raster images reliably; a live canvas or a remote
 * chart page is never needed once the file is saved.
 */

import { renderChartSvg, type RenderedChart } from "./chartSvg";
import type { ChartSpec } from "./trialCharts";

export interface RasterImage {
  dataUrl: string;
  bytes: Uint8Array;
  width: number;
  height: number;
  rendered: RenderedChart;
}

function loadImage(src: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error("Chart image could not be decoded"));
    img.src = src;
  });
}

function base64ToBytes(base64: string): Uint8Array {
  const binary = atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return bytes;
}

export async function rasterizeChart(
  chart: ChartSpec,
  scale = 2
): Promise<RasterImage> {
  const rendered = renderChartSvg(chart);
  const dataUrl = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(rendered.svg)}`;
  const img = await loadImage(dataUrl);

  const canvas = document.createElement("canvas");
  canvas.width = Math.round(rendered.width * scale);
  canvas.height = Math.round(rendered.height * scale);
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("This browser cannot rasterise charts");
  ctx.fillStyle = "#ffffff";
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.drawImage(img, 0, 0, canvas.width, canvas.height);

  const png = canvas.toDataURL("image/png");
  return {
    dataUrl: png,
    bytes: base64ToBytes(png.split(",")[1] ?? ""),
    width: canvas.width,
    height: canvas.height,
    rendered,
  };
}

export async function rasterizeCharts(
  charts: ChartSpec[],
  scale = 2
): Promise<Map<string, RasterImage>> {
  const out = new Map<string, RasterImage>();
  for (const chart of charts) {
    try {
      out.set(chart.id, await rasterizeChart(chart, scale));
    } catch {
      // A chart that cannot be rasterised is reported by the caller as an
      // explicit omission rather than silently dropping out of the document.
      out.delete(chart.id);
    }
  }
  return out;
}
