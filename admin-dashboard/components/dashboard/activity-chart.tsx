import { formatDateShort, formatInteger } from "@/lib/dashboard/format";
import type { ActivityPoint } from "@/lib/dashboard/types";

export interface ActivityChartProps {
  data: ActivityPoint[];
}

const WIDTH = 480;
const HEIGHT = 220;
const PADDING_X = 28;
const PADDING_Y = 24;

export function ActivityChart({ data }: ActivityChartProps) {
  if (data.length === 0) {
    return <p className="text-sm text-slate-500">No activity data.</p>;
  }

  const max = Math.max(...data.map((p) => p.active_users + p.new_users), 1);
  const innerWidth = WIDTH - PADDING_X * 2;
  const innerHeight = HEIGHT - PADDING_Y * 2;
  const slotWidth = innerWidth / data.length;
  const barWidth = Math.max(8, slotWidth * 0.55);

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-4 text-xs text-slate-500 dark:text-slate-400">
        <span className="inline-flex items-center gap-1">
          <span className="inline-block h-2 w-2 rounded-sm bg-brand-500" /> Active users
        </span>
        <span className="inline-flex items-center gap-1">
          <span className="inline-block h-2 w-2 rounded-sm bg-emerald-500" /> New users
        </span>
      </div>
      <svg
        role="img"
        aria-label="Active and new users over the last 7 days"
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        className="h-56 w-full"
        preserveAspectRatio="none"
      >
        {[0, 0.5, 1].map((ratio) => {
          const y = PADDING_Y + innerHeight * (1 - ratio);
          return (
            <g key={ratio}>
              <line
                x1={PADDING_X}
                x2={WIDTH - PADDING_X}
                y1={y}
                y2={y}
                stroke="currentColor"
                strokeOpacity="0.12"
                strokeDasharray="4 4"
              />
              <text
                x={PADDING_X - 6}
                y={y + 3}
                textAnchor="end"
                className="fill-slate-400 text-[10px] dark:fill-slate-500"
              >
                {formatInteger(max * ratio)}
              </text>
            </g>
          );
        })}
        {data.map((point, idx) => {
          const totalHeight = ((point.active_users + point.new_users) / max) * innerHeight;
          const newHeight = (point.new_users / max) * innerHeight;
          const activeHeight = totalHeight - newHeight;
          const slotX = PADDING_X + idx * slotWidth + (slotWidth - barWidth) / 2;
          const baseY = PADDING_Y + innerHeight;
          return (
            <g key={point.date}>
              <rect
                x={slotX}
                y={baseY - activeHeight}
                width={barWidth}
                height={activeHeight}
                fill="#6366f1"
                rx={3}
              />
              <rect
                x={slotX}
                y={baseY - totalHeight}
                width={barWidth}
                height={newHeight}
                fill="#10b981"
                rx={3}
              />
              <text
                x={slotX + barWidth / 2}
                y={HEIGHT - 6}
                textAnchor="middle"
                className="fill-slate-500 text-[10px] dark:fill-slate-400"
              >
                {formatDateShort(point.date)}
              </text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}
