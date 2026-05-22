import { formatDateShort, formatUsd } from "@/lib/dashboard/format";
import type { RevenuePoint } from "@/lib/dashboard/types";

export interface RevenueChartProps {
  data: RevenuePoint[];
}

const WIDTH = 720;
const HEIGHT = 220;
const PADDING_X = 32;
const PADDING_Y = 24;

export function RevenueChart({ data }: RevenueChartProps) {
  if (data.length === 0) {
    return <p className="text-sm text-slate-500">No revenue yet.</p>;
  }

  const max = Math.max(...data.map((p) => p.usd), 1);
  const min = Math.min(...data.map((p) => p.usd), 0);
  const span = Math.max(max - min, 1);

  const innerWidth = WIDTH - PADDING_X * 2;
  const innerHeight = HEIGHT - PADDING_Y * 2;
  const stepX = data.length > 1 ? innerWidth / (data.length - 1) : 0;

  const points = data.map((point, index) => {
    const x = PADDING_X + index * stepX;
    const y = PADDING_Y + innerHeight - ((point.usd - min) / span) * innerHeight;
    return { ...point, x, y };
  });

  const linePath = points
    .map((p, i) => `${i === 0 ? "M" : "L"} ${p.x.toFixed(2)} ${p.y.toFixed(2)}`)
    .join(" ");

  const firstPoint = points[0];
  const lastPoint = points[points.length - 1];
  const baselineY = (PADDING_Y + innerHeight).toFixed(2);
  const areaPath =
    firstPoint && lastPoint
      ? `${linePath} L ${lastPoint.x.toFixed(2)} ${baselineY} L ${firstPoint.x.toFixed(2)} ${baselineY} Z`
      : "";

  const total = data.reduce((sum, p) => sum + p.usd, 0);
  const peak = Math.max(...data.map((p) => p.usd));

  const tickEvery = Math.max(1, Math.floor(data.length / 6));

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between text-sm text-slate-500 dark:text-slate-400">
        <span>
          Total: <strong className="text-slate-900 dark:text-slate-100">{formatUsd(total)}</strong>
        </span>
        <span>
          Peak day: <strong className="text-slate-900 dark:text-slate-100">{formatUsd(peak)}</strong>
        </span>
      </div>
      <svg
        role="img"
        aria-label="Revenue over the last 30 days"
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        className="h-56 w-full"
        preserveAspectRatio="none"
      >
        <defs>
          <linearGradient id="revenue-fill" x1="0" x2="0" y1="0" y2="1">
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
              strokeOpacity="0.12"
              strokeDasharray="4 4"
            />
          );
        })}
        {areaPath && <path d={areaPath} fill="url(#revenue-fill)" />}
        {linePath && <path d={linePath} fill="none" stroke="#4f46e5" strokeWidth={2} />}
        {points.map((p, idx) => {
          if (idx % tickEvery !== 0 && idx !== points.length - 1) return null;
          return (
            <g key={p.date}>
              <circle cx={p.x} cy={p.y} r={3} fill="#4f46e5" />
              <text
                x={p.x}
                y={HEIGHT - 6}
                textAnchor="middle"
                className="fill-slate-500 text-[10px] dark:fill-slate-400"
              >
                {formatDateShort(p.date)}
              </text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}
