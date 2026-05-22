import { formatInteger, formatNumberCompact, formatPercent } from "@/lib/dashboard/format";
import type { ServiceKey, ServiceUsageSlice } from "@/lib/dashboard/types";

export interface UsageChartProps {
  data: ServiceUsageSlice[];
}

const COLORS: Record<ServiceKey, string> = {
  image: "#6366f1",
  video: "#f59e0b",
  text: "#10b981",
};

const LABELS: Record<ServiceKey, string> = {
  image: "Image",
  video: "Video",
  text: "Text",
};

const SIZE = 200;
const RADIUS = 80;
const STROKE = 28;

function describeArc(startAngle: number, endAngle: number): string {
  const cx = SIZE / 2;
  const cy = SIZE / 2;
  const start = polar(cx, cy, RADIUS, endAngle);
  const end = polar(cx, cy, RADIUS, startAngle);
  const largeArc = endAngle - startAngle > Math.PI ? 1 : 0;
  return ["M", start.x, start.y, "A", RADIUS, RADIUS, 0, largeArc, 0, end.x, end.y].join(" ");
}

function polar(cx: number, cy: number, radius: number, angle: number): { x: number; y: number } {
  return {
    x: cx + radius * Math.cos(angle - Math.PI / 2),
    y: cy + radius * Math.sin(angle - Math.PI / 2),
  };
}

export function UsageChart({ data }: UsageChartProps) {
  const total = data.reduce((sum, slice) => sum + slice.tokens, 0);

  if (total === 0) {
    return <p className="text-sm text-slate-500">No usage yet.</p>;
  }

  const arcs = data.reduce<{ slice: ServiceUsageSlice; start: number; end: number }[]>((segments, slice) => {
    const start = segments.at(-1)?.end ?? 0;
    const angle = (slice.tokens / total) * Math.PI * 2;
    return [...segments, { slice, start, end: start + angle }];
  }, []);

  return (
    <div className="flex flex-col items-center gap-4 sm:flex-row sm:items-center sm:gap-6">
      <svg
        role="img"
        aria-label="Tokens consumed by service"
        viewBox={`0 0 ${SIZE} ${SIZE}`}
        className="h-44 w-44 shrink-0"
      >
        <circle
          cx={SIZE / 2}
          cy={SIZE / 2}
          r={RADIUS}
          fill="none"
          stroke="currentColor"
          strokeOpacity="0.08"
          strokeWidth={STROKE}
        />
        {arcs.map(({ slice, start, end }) => (
          <path
            key={slice.service}
            d={describeArc(start, end)}
            fill="none"
            stroke={COLORS[slice.service]}
            strokeWidth={STROKE}
            strokeLinecap="butt"
          />
        ))}
        <text
          x="50%"
          y="50%"
          textAnchor="middle"
          dominantBaseline="central"
          className="fill-slate-700 text-sm font-semibold dark:fill-slate-200"
        >
          {formatNumberCompact(total)}
        </text>
      </svg>
      <ul className="grid w-full grid-cols-1 gap-2 text-sm">
        {data.map((slice) => {
          const share = (slice.tokens / total) * 100;
          return (
            <li
              key={slice.service}
              className="flex items-center justify-between rounded-md bg-slate-50 px-3 py-2 dark:bg-slate-800/60"
            >
              <span className="flex items-center gap-2">
                <span
                  className="inline-block h-2 w-2 rounded-sm"
                  style={{ backgroundColor: COLORS[slice.service] }}
                  aria-hidden
                />
                <span className="font-medium text-slate-700 dark:text-slate-200">{LABELS[slice.service]}</span>
              </span>
              <span className="flex items-baseline gap-2 tabular-nums">
                <span className="text-slate-900 dark:text-slate-100">{formatInteger(slice.tokens)}</span>
                <span className="text-xs text-slate-500 dark:text-slate-400">{formatPercent(share)}</span>
              </span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
