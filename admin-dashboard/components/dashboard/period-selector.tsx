"use client";

import { cn } from "@/lib/utils";
import { PERIODS, type PeriodKey } from "@/lib/dashboard/types";

const LABELS: Record<PeriodKey, string> = {
  "1d": "24h",
  "7d": "7d",
  "30d": "30d",
  "90d": "90d",
};

export interface PeriodSelectorProps {
  value: PeriodKey;
  onChange: (next: PeriodKey) => void;
  disabled?: boolean;
}

export function PeriodSelector({ value, onChange, disabled }: PeriodSelectorProps) {
  return (
    <div
      role="tablist"
      aria-label="Dashboard period"
      className="inline-flex rounded-md border border-slate-200 bg-white p-1 shadow-sm dark:border-slate-700 dark:bg-slate-900"
    >
      {PERIODS.map((period) => {
        const active = period === value;
        return (
          <button
            key={period}
            type="button"
            role="tab"
            aria-selected={active}
            disabled={disabled}
            onClick={() => onChange(period)}
            className={cn(
              "rounded px-3 py-1 text-sm font-medium transition-colors",
              active
                ? "bg-brand-600 text-white shadow"
                : "text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800",
              disabled && "cursor-not-allowed opacity-60",
            )}
          >
            {LABELS[period]}
          </button>
        );
      })}
    </div>
  );
}
