"use client";

import { formatDateShort, formatInteger } from "@/lib/dashboard/format";
import type { RetentionRow } from "@/lib/admin-analytics/types";
import { cn } from "@/lib/utils";

interface RetentionMatrixProps {
  rows: RetentionRow[];
  weeks: number;
}

function cellTone(rate: number): string {
  if (rate >= 0.7) return "bg-emerald-500/80 text-white";
  if (rate >= 0.5) return "bg-emerald-400/70 text-white";
  if (rate >= 0.3) return "bg-amber-300/70 text-amber-950";
  if (rate >= 0.15) return "bg-amber-200/70 text-amber-900";
  if (rate > 0) return "bg-rose-200/60 text-rose-900";
  return "bg-slate-100 text-slate-400 dark:bg-slate-800 dark:text-slate-500";
}

export function RetentionMatrix({ rows, weeks }: RetentionMatrixProps) {
  if (rows.length === 0) {
    return (
      <p className="text-sm text-slate-500 dark:text-slate-400">
        No retention data in the selected range.
      </p>
    );
  }
  const headers = Array.from({ length: weeks }, (_, i) => `W${i}`);
  return (
    <div className="overflow-x-auto">
      <table className="min-w-full text-xs">
        <thead className="text-slate-500 dark:text-slate-400">
          <tr>
            <th scope="col" className="px-2 py-2 text-left font-medium">
              Cohort
            </th>
            <th scope="col" className="px-2 py-2 text-right font-medium">
              Size
            </th>
            {headers.map((h) => (
              <th key={h} scope="col" className="px-2 py-2 text-center font-medium">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.cohort} className="border-t border-slate-200 dark:border-slate-800">
              <td className="px-2 py-2 font-medium text-slate-700 dark:text-slate-200">
                {formatDateShort(row.cohort)}
              </td>
              <td className="px-2 py-2 text-right text-slate-500 dark:text-slate-400">
                {formatInteger(row.cohort_size)}
              </td>
              {headers.map((_, idx) => {
                const rate = row.rates[idx] ?? 0;
                const retained = row.retained[idx] ?? 0;
                return (
                  <td key={idx} className="px-1 py-1 text-center">
                    <div
                      className={cn(
                        "mx-auto inline-flex h-8 w-12 items-center justify-center rounded-md font-medium",
                        cellTone(rate),
                      )}
                      title={`${formatInteger(retained)} / ${formatInteger(row.cohort_size)} users`}
                    >
                      {rate === 0 && retained === 0 ? "—" : `${(rate * 100).toFixed(0)}%`}
                    </div>
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
