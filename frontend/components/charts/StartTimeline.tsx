"use client";

import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import useIsMounted from "./useIsMounted";

interface Props {
  data: { period: string; count: number }[];
  granularity: string | null;
  height?: number;
}

export default function StartTimeline({ data, granularity, height = 240 }: Props) {
  const mounted = useIsMounted();

  if (data.length === 0) {
    return (
      <p className="py-8 text-center text-sm text-slate-400">
        No timeline is shown for this result set.
      </p>
    );
  }

  if (!mounted) {
    return (
      <div
        style={{ height }}
        className="flex h-full items-center justify-center text-xs text-slate-400"
        aria-hidden="true"
      >
        Preparing chart…
      </div>
    );
  }

  return (
    <div
      style={{ height }}
      role="img"
      aria-label={`Clinical trial start dates grouped by ${granularity ?? "period"}`}
    >
      <ResponsiveContainer width="100%" height="100%">
        <LineChart
          data={data}
          margin={{ top: 8, right: 16, bottom: 4, left: 0 }}
        >
          <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
          <XAxis
            dataKey="period"
            tick={{ fontSize: 10, fill: "#475569" }}
            interval="preserveStartEnd"
            minTickGap={18}
          />
          <YAxis
            allowDecimals={false}
            tick={{ fontSize: 11, fill: "#64748b" }}
            width={34}
          />
          <Tooltip
            formatter={(value: number) => [
              `${value} trial${value === 1 ? "" : "s"}`,
              "Started",
            ]}
          />
          <Line
            type="monotone"
            dataKey="count"
            stroke="#0ea5e9"
            strokeWidth={2}
            dot={{ r: 2.5 }}
            activeDot={{ r: 4 }}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
