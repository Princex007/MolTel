"use client";

// Recharts measures its container in a layout effect, so server markup and the
// first client paint disagree. Charts render a placeholder until mounted.
import { useEffect, useState } from "react";

export default function useIsMounted(): boolean {
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);
  return mounted;
}
