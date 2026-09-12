"use client";

import type { ReactNode } from "react";
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  type TooltipValueType,
} from "recharts";

function formatNumber(value: number | null | undefined, digits = 3): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "-";
  }
  return value.toFixed(digits);
}

export interface MultiReturnPeakChartProps {
  peaks: Record<string, unknown>[];
}

/**
 * 多回击峰值分布图（recharts 约 400KB）。
 * 单独成模块并通过 next/dynamic 按需加载：详情抽屉打开且有多回击数据时才下载图表库。
 */
export default function MultiReturnPeakChart({ peaks }: MultiReturnPeakChartProps) {
  const data = peaks.map((peak, idx) => ({
    index: idx + 1,
    time_us: Number(peak.time_us) || 0,
    current_ka: Number(peak.current_ka) || 0,
  }));

  return (
    <ResponsiveContainer width="100%" height={320}>
      <LineChart data={data}>
        <CartesianGrid strokeDasharray="3 3" />
        <XAxis dataKey="index" label={{ value: "回击序号", position: "insideBottomRight", offset: -5 }} />
        <YAxis label={{ value: "峰值电流 (kA)", angle: -90, position: "insideLeft", offset: 10 }} />
        <Tooltip
          formatter={(value: TooltipValueType | undefined, name?: string | number) => {
            if (name === "current_ka") return [formatNumber(Number(value), 3), "峰值电流 (kA)"] as [ReactNode, string | number];
            if (name === "time_us") return [formatNumber(Number(value), 2), "时间 (μs)"] as [ReactNode, string | number];
            return [value, name ?? ""] as [ReactNode, string | number];
          }}
          labelFormatter={(label) => `回击 ${label}`}
        />
        <Legend />
        <Line type="monotone" dataKey="current_ka" stroke="#1890ff" name="峰值电流 (kA)" strokeWidth={2} dot={{ r: 4 }} />
      </LineChart>
    </ResponsiveContainer>
  );
}
