"use client";

import { formatDateShort, formatUsd } from "@/lib/dashboard/format";
import type { RevenuePoint } from "@/lib/admin-analytics/types";

interface RevenueTrendChartProps {
  points: RevenuePoint[];
}

const WIDTH = 720;
const HEIGHT = 240;
const PADDING_X = 36;
const PADDING_Y = 24;

export function RevenueTrendChart({ points }: RevenueTrendChartProps) {
  if (points.length === 0) {
    return (
      <p className="text-sm text-slate-500 dark:text-slate-400">
        No revenue in the selected range.
      </p>
    );
  }

  const usd = points.map((p) => Number.parseFloat(p.usd) || 0);
  const max = Math.max(...usd, 1);
  const min = Math.min(...usd, 0);
  const span = Math.max(max - min, 1);

  const innerWidth = WIDTH - PADDING_X * 2;
  const innerHeight = HEIGHT - PADDING_Y * 2;
  const stepX = points.length > 1 ? innerWidth / (points.length - 1) : 0;

  const projected = points.map((point, index) => {
    const value = usd[index] ?? 0;
    const x = PADDING_X + index * stepX;
    const y = PADDING_Y + innerHeight - ((value - min) / span) * innerHeight;
    return { ...point, value, x, y };
  });

  const linePath = projected
    .map((p, i) => `${i === 0 ? "M" : "L"} ${p.x.toFixed(2)} ${p.y.toFixed(2)}`)
    .join(" ");

  const baselineY = (PADDING_Y + innerHeight).toFixed(2);
  const areaPath =
    projected.length > 0
      ? `${linePath} L ${projected[projected.length - 1]!.x.toFixed(2)} ${baselineY} L ${projected[0]!.x.toFixed(2)} ${baselineY} Z`
      : "";

  const tickEvery = Math.max(1, Math.floor(projected.length / 6));

  return (
    <svg
      role="img"
      aria-label="Revenue over the selected range"
      viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
      className="h-60 w-full text-slate-400 dark:text-slate-500"
      preserveAspectRatio="none"
    >
      <defs>
        <linearGradient id="analytics-revenue-fill" x1="0" x2="0" y1="0" y2="1">
          <stop offset="0%" stopColor="#6366f1" stopOpacity="0.32" />
          <stop offset="100%" stopColor="#6366f1" stopOpacity="0" />
        </linearGradient>
      </defs>
      {[0, 0.25, 0.5, 0.75, 1].map((ratio) => {
        const y = PADDING_Y + innerHeight * ratio;
        return (
          <line
            key={ratio}
            x1={PADDING_X}
            x2={WIDTH - PADDING_X}
            y1={y}
            y2={y}
            stroke="currentColor"
            strokeOpacity="0.18"
            strokeDasharray="4 4"
          />
        );
      })}
      {areaPath && <path d={areaPath} fill="url(#analytics-revenue-fill)" />}
      {linePath && <path d={linePath} fill="none" stroke="#4f46e5" strokeWidth={2} />}
      {projected.map((p, idx) => {
        if (idx % tickEvery !== 0 && idx !== projected.length - 1) return null;
        return (
          <g key={p.bucket}>
            <circle cx={p.x} cy={p.y} r={3} fill="#4f46e5">
              <title>
                {formatDateShort(p.bucket)} — {formatUsd(p.value, { precise: true })}
              </title>
            </circle>
            <text
              x={p.x}
              y={HEIGHT - 6}
              textAnchor="middle"
              className="fill-slate-500 text-[10px] dark:fill-slate-400"
            >
              {formatDateShort(p.bucket)}
            </text>
          </g>
        );
      })}
    </svg>
  );
}
