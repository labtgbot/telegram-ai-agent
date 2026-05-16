import { Card, CardSubtitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import { deltaTone, formatPercent } from "@/lib/dashboard/format";

export interface KpiCardProps {
  label: string;
  value: string;
  hint?: string;
  delta_pct: number;
  /** Hide trend pill when the metric isn't comparable (e.g. lifetime totals). */
  hideDelta?: boolean;
}

const TONE_CLASSES: Record<"up" | "down" | "flat", string> = {
  up: "bg-emerald-100 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300",
  down: "bg-rose-100 text-rose-700 dark:bg-rose-500/15 dark:text-rose-300",
  flat: "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300",
};

const TONE_GLYPH: Record<"up" | "down" | "flat", string> = {
  up: "▲",
  down: "▼",
  flat: "→",
};

export function KpiCard({ label, value, hint, delta_pct, hideDelta }: KpiCardProps) {
  const tone = deltaTone(delta_pct);
  return (
    <Card aria-label={`${label} KPI`} className="flex flex-col gap-2">
      <div className="flex items-start justify-between gap-3">
        <CardSubtitle className="font-medium text-slate-600 dark:text-slate-300">{label}</CardSubtitle>
        {!hideDelta && (
          <span
            className={cn(
              "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium tabular-nums",
              TONE_CLASSES[tone],
            )}
            aria-label={`${formatPercent(delta_pct, { sign: true })} versus previous period`}
            data-tone={tone}
          >
            <span aria-hidden>{TONE_GLYPH[tone]}</span>
            {formatPercent(Math.abs(delta_pct))}
          </span>
        )}
      </div>
      <p className="text-3xl font-semibold tabular-nums text-slate-900 dark:text-slate-100">{value}</p>
      {hint && <p className="text-xs text-slate-500 dark:text-slate-400">{hint}</p>}
    </Card>
  );
}
