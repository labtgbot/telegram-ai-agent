import { formatInteger, formatRelative, formatStars, formatUsd } from "@/lib/dashboard/format";
import { cn } from "@/lib/utils";
import type { TransactionRow, TransactionType } from "@/lib/dashboard/types";

export interface TransactionsListProps {
  rows: TransactionRow[];
}

const TYPE_LABELS: Record<TransactionType, string> = {
  purchase: "Purchase",
  refund: "Refund",
  manual_bonus: "Manual",
  bonus: "Bonus",
};

const TYPE_TONE: Record<TransactionType, string> = {
  purchase: "bg-emerald-100 text-emerald-800 dark:bg-emerald-500/20 dark:text-emerald-200",
  refund: "bg-rose-100 text-rose-800 dark:bg-rose-500/20 dark:text-rose-200",
  manual_bonus: "bg-amber-100 text-amber-800 dark:bg-amber-500/20 dark:text-amber-200",
  bonus: "bg-brand-100 text-brand-800 dark:bg-brand-500/20 dark:text-brand-100",
};

export function TransactionsList({ rows }: TransactionsListProps) {
  if (rows.length === 0) {
    return <p className="text-sm text-slate-500">No transactions yet.</p>;
  }

  return (
    <ul role="list" className="divide-y divide-slate-200 dark:divide-slate-800">
      {rows.map((row) => (
        <li key={row.id} className="flex items-center justify-between gap-3 py-3">
          <div className="min-w-0">
            <p className="flex items-center gap-2 text-sm font-medium text-slate-900 dark:text-slate-100">
              <span className={cn("rounded-full px-2 py-0.5 text-[10px] uppercase tracking-wide", TYPE_TONE[row.transaction_type])}>
                {TYPE_LABELS[row.transaction_type]}
              </span>
              <span className="truncate">{row.username ? `@${row.username}` : `user #${row.user_id}`}</span>
            </p>
            <p className="text-xs text-slate-500 dark:text-slate-400">
              <span className="tabular-nums">#{row.id}</span> · {formatRelative(row.created_at)}
            </p>
          </div>
          <div className="text-right">
            <p
              className={cn(
                "text-sm font-semibold tabular-nums",
                row.tokens_amount >= 0 ? "text-slate-900 dark:text-slate-100" : "text-rose-600 dark:text-rose-300",
              )}
            >
              {row.tokens_amount >= 0 ? "+" : ""}
              {formatInteger(row.tokens_amount)} tokens
            </p>
            <p className="text-xs text-slate-500 dark:text-slate-400">
              {row.usd_amount !== null ? formatUsd(row.usd_amount, { precise: true }) : "—"}
              {row.stars_amount !== null && (
                <>
                  {" · "}
                  {formatStars(row.stars_amount)}
                </>
              )}
            </p>
          </div>
        </li>
      ))}
    </ul>
  );
}
