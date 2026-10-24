/**
 * Single source of colour truth so a phase or status keeps the same hue in
 * every chart, on screen and in exports.
 */

const PHASE_COLORS: Record<string, string> = {
  "Phase 1": "#4f46e5",
  "Phase 2": "#0891b2",
  "Phase 3": "#059669",
  "Phase 4": "#d97706",
};

// Not a development stage — rendered in greys so a reader cannot mistake it for one.
const NOT_APPLICABLE_COLOR = "#a8b3c1";
const UNKNOWN_COLOR = "#d2d8e0";

const FALLBACK_PALETTE = ["#7c3aed", "#db2777", "#0284c7", "#ca8a04", "#16a34a"];

const STATUS_COLORS: Record<string, string> = {
  RECRUITING: "#059669",
  ENROLLING_BY_INVITATION: "#10b981",
  ACTIVE_NOT_RECRUITING: "#0891b2",
  NOT_YET_RECRUITING: "#d97706",
  COMPLETED: "#475569",
  TERMINATED: "#dc2626",
  WITHDRAWN: "#ef4444",
  SUSPENDED: "#f59e0b",
  UNKNOWN: "#cbd5e1",
  AVAILABLE: "#94a3b8",
  "TEMPORARILY_NOT_AVAILABLE": "#f97316",
};

function hashIndex(value: string, size: number): number {
  let h = 0;
  for (let i = 0; i < value.length; i++) h = (h * 31 + value.charCodeAt(i)) >>> 0;
  return h % size;
}

export function colorForPhase(label: string): string {
  const exact = PHASE_COLORS[label];
  if (exact) return exact;
  const norm = label.toLowerCase();
  if (norm.includes("not applicable")) return NOT_APPLICABLE_COLOR;
  if (norm.includes("unknown") || norm.includes("not reported")) return UNKNOWN_COLOR;
  // Combined buckets ("Phase 1 + Phase 2") and any registry-only value.
  return FALLBACK_PALETTE[hashIndex(norm, FALLBACK_PALETTE.length)];
}

export function colorForStatus(label: string): string {
  const key = label.toUpperCase().replace(/\s+/g, "_");
  if (STATUS_COLORS[key]) return STATUS_COLORS[key];
  return FALLBACK_PALETTE[hashIndex(key, FALLBACK_PALETTE.length)];
}

export function colorForSeries(label: string): string {
  return FALLBACK_PALETTE[hashIndex(label, FALLBACK_PALETTE.length)];
}

export const META_COLORS = { notApplicable: NOT_APPLICABLE_COLOR, unknown: UNKNOWN_COLOR };
