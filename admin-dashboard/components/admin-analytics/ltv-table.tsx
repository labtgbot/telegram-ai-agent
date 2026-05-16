"use client";

import { formatDateShort, formatInteger, formatUsd } from "@/lib/dashboard/format";
import type { LtvCohort } from "@/lib/admin-analytics/types";

interface LtvTableProps {
  cohorts: LtvCohort[];
}

function pct(value: number): string {
  return `${(value * 100).toFixed(1)}%`;
}

export function LtvTable({ cohorts }: LtvTableProps) {
  if (cohorts.length === 0) {
    return (
      <p className="text-sm text-slate-500 dark:text-slate-400">
        No registration cohorts in the lookback window.
      </p>
    );
  }
  return (
    <div className="overflow-x-auto">
      <table className="min-w-full text-sm">
        <thead className="text-xs uppercase tracking-wide text-slate-500 dark:text-slate-400">
          <tr>
            <th scope="col" className="px-3 py-2 text-left font-medium">
              Cohort
            </th>
            <th scope="col" className="px-3 py-2 text-right font-medium">
              Size
            </th>
            <th scope="col" className="px-3 py-2 text-right font-medium">
              Paying
            </th>
            <th scope="col" className="px-3 py-2 text-right font-medium">
              Paying rate
            </th>
            <th scope="col" className="px-3 py-2 text-right font-medium">
              Revenue ⭐
            </th>
            <th scope="col" className="px-3 py-2 text-right font-medium">
              Revenue $
            </th>
            <th scope="col" className="px-3 py-2 text-right font-medium">
              LTV $
            </th>
            <th scope="col" className="px-3 py-2 text-right font-medium">
              ARPPU $
            </th>
          </tr>
        </thead>
        <tbody>
          {cohorts.map((c) => {
            const payingRate = c.cohort_size > 0 ? c.paying_users / c.cohort_size : 0;
            const arppuUsd = c.paying_users > 0 ? Number.parseFloat(c.revenue_usd) / c.paying_users : 0;
            return (
              <tr
                key={c.cohort}
                className="border-t border-slate-200 dark:border-slate-800"
              >
                <td className="px-3 py-2 font-medium text-slate-800 dark:text-slate-100">
                  {formatDateShort(c.cohort)}
                </td>
                <td className="px-3 py-2 text-right text-slate-700 dark:text-slate-200">
                  {formatInteger(c.cohort_size)}
                </td>
                <td className="px-3 py-2 text-right text-slate-700 dark:text-slate-200">
                  {formatInteger(c.paying_users)}
                </td>
                <td className="px-3 py-2 text-right text-slate-500 dark:text-slate-400">
                  {pct(payingRate)}
                </td>
                <td className="px-3 py-2 text-right text-slate-700 dark:text-slate-200">
                  {formatInteger(c.revenue_stars)}
                </td>
                <td className="px-3 py-2 text-right text-slate-700 dark:text-slate-200">
                  {formatUsd(Number.parseFloat(c.revenue_usd), { precise: true })}
                </td>
                <td className="px-3 py-2 text-right font-medium text-indigo-600 dark:text-indigo-300">
                  {formatUsd(c.ltv_usd, { precise: true })}
                </td>
                <td className="px-3 py-2 text-right text-slate-500 dark:text-slate-400">
                  {formatUsd(arppuUsd, { precise: true })}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
