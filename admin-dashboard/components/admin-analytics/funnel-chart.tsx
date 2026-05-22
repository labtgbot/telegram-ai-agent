"use client";

import { formatInteger } from "@/lib/dashboard/format";
import type { FunnelStage } from "@/lib/admin-analytics/types";

interface FunnelChartProps {
  stages: FunnelStage[];
}

function formatPct(value: number): string {
  return `${(value * 100).toFixed(1)}%`;
}

export function FunnelChart({ stages }: FunnelChartProps) {
  if (stages.length === 0) {
    return <p className="text-sm text-slate-500 dark:text-slate-400">No funnel data.</p>;
  }
  const top = stages[0]?.users ?? 0;

  return (
    <ol className="space-y-2">
      {stages.map((stage, idx) => {
        const widthPct = top > 0 ? Math.max(2, (stage.users / top) * 100) : 0;
        return (
          <li
            key={stage.key}
            className="rounded-md border border-slate-200 bg-white p-3 shadow-sm dark:border-slate-800 dark:bg-slate-900"
          >
            <div className="flex items-center justify-between gap-3 text-sm">
              <div className="flex items-baseline gap-2">
                <span className="text-xs font-mono text-slate-400">#{idx + 1}</span>
                <span className="font-medium text-slate-800 dark:text-slate-100">
                  {stage.label}
                </span>
              </div>
              <div className="flex items-baseline gap-3 text-xs text-slate-500 dark:text-slate-400">
                <span>
                  <strong className="text-slate-900 dark:text-slate-100">
                    {formatInteger(stage.users)}
                  </strong>{" "}
                  users
                </span>
                <span title="Conversion from the previous stage">
                  ↳ {formatPct(stage.conversion_from_previous)}
                </span>
                <span title="Conversion from the top of the funnel">
                  ▲ {formatPct(stage.conversion_from_top)}
                </span>
              </div>
            </div>
            <div className="mt-2 h-3 w-full overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800">
              <div
                className="h-full rounded-full bg-indigo-500"
                style={{ width: `${widthPct}%` }}
                aria-hidden
              />
            </div>
          </li>
        );
      })}
    </ol>
  );
}
