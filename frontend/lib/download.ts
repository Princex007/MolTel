/**
 * Trigger a real browser file download. Nothing here opens a print dialog.
 */

export function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.rel = "noopener";
  document.body.appendChild(a);
  a.click();
  a.remove();
  // Chrome needs the click to land before the object URL goes away.
  setTimeout(() => URL.revokeObjectURL(url), 4000);
}

export function safeSegment(value: string, max = 120): string {
  return value.replace(/[^\x20-\x7E]/g, "").slice(0, max);
}
