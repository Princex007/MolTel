"use client";

import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  LabelList,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import useIsMounted from "./useIsMounted";

export interface Bucket {
  label: string;
  count: number;
  /** When set, the bar uses this colour so a phase keeps it in every chart. */
  color?: string;
}

interface BarBreakdownProps {
  data: Bucket[];
  fill?: string;
  activeLabel?: string | null;
  onBarClick?: (label: string) => void;
  height?: number;
  rotated?: boolean;
  ariaLabel: string;
  /** Wording for the tooltip and axis, e.g. "trials" or "candidates". */
  unit?: string;
}

const PLACEHOLDER =
  "flex h-full items-center justify-center text-xs text-slate-400";

/**
 * Bar chart over the dashboard buckets. Bars are clickable so a phase or status
 * can be used to filter the study list underneath it.
 */
export default function BarBreakdown({
  data,
  fill = "#4f46e5",
  activeLabel,
  onBarClick,
  height = 240,
  rotated = false,
  ariaLabel,
  unit = "trials",
}: BarBreakdownProps) {
  const mounted = useIsMounted();

  if (data.length === 0) {
    return (
      <p className="py-8 text-center text-sm text-slate-400">
        No records fall into this view.
      </p>
    );
  }

  if (!mounted) {
    return (
      <div style={{ height }} className={PLACEHOLDER} aria-hidden="true">
        Preparing chart…
      </div>
    );
  }

  const maxCount = Math.max(...data.map((d) => d.count), 1);
  const labelWidth = rotated
    ? Math.min(190, Math.max(...data.map((d) => d.label.length)) * 6.4)
    : undefined;

  return (
    <div style={{ height }} role="img" aria-label={ariaLabel}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart
          data={data}
          layout={rotated ? "vertical" : "horizontal"}
          margin={{ top: 8, right: 12, bottom: 8, left: rotated ? 4 : 4 }}
        >
          <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
          {rotated ? (
            <>
              <XAxis
                type="number"
                domain={[0, maxCount]}
                allowDecimals={false}
                tick={{ fontSize: 11, fill: "#64748b" }}
              />
              <YAxis
                type="category"
                dataKey="label"
                width={labelWidth}
                tick={{ fontSize: 11, fill: "#475569" }}
                interval={0}
              />
            </>
          ) : (
            <>
              <XAxis
                dataKey="label"
                tick={{ fontSize: 10, fill: "#475569" }}
                interval={0}
                angle={-18}
                textAnchor="end"
                height={54}
              />
              <YAxis
                allowDecimals={false}
                tick={{ fontSize: 11, fill: "#64748b" }}
                width={34}
              />
            </>
          )}
          <Tooltip
            cursor={{ fill: "rgba(79,70,229,0.06)" }}
            formatter={(value: number, name: string) => [
              `${value} ${value === 1 ? unit.replace(/s$/, "") : unit}`,
              name === "count" ? "Count" : name,
            ]}
            labelFormatter={(label) => `${label}`}
          />
          <Bar
            dataKey="count"
            fill={fill}
            isAnimationActive={false}
            radius={rotated ? [0, 3, 3, 0] : [3, 3, 0, 0]}
            onClick={(entry: { label?: string }) =>
              entry?.label && onBarClick?.(entry.label)
            }
            cursor={onBarClick ? "pointer" : undefined}
          >
            <LabelList
              dataKey="count"
              position={rotated ? "right" : "top"}
              style={{ fontSize: 11, fill: "#334155" }}
            />
            {data.map((d) => (
              <Cell
                key={d.label}
                fill={
                  activeLabel && activeLabel !== d.label ? "#c7d2fe" : d.color ?? fill
                }
              />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
