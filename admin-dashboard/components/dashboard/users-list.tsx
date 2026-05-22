import { formatRelative } from "@/lib/dashboard/format";
import type { NewUserRow } from "@/lib/dashboard/types";

export interface UsersListProps {
  rows: NewUserRow[];
}

function initials(row: NewUserRow): string {
  if (row.first_name) {
    return row.first_name.slice(0, 1).toUpperCase();
  }
  if (row.username) return row.username.slice(0, 1).toUpperCase();
  return "?";
}

function displayName(row: NewUserRow): string {
  if (row.first_name) return row.first_name;
  if (row.username) return `@${row.username}`;
  return `user #${row.id}`;
}

export function UsersList({ rows }: UsersListProps) {
  if (rows.length === 0) {
    return <p className="text-sm text-slate-500">No new users yet.</p>;
  }

  return (
    <ul role="list" className="divide-y divide-slate-200 dark:divide-slate-800">
      {rows.map((row) => (
        <li key={row.id} className="flex items-center gap-3 py-3">
          <span
            className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-brand-100 text-sm font-semibold text-brand-700 dark:bg-brand-500/20 dark:text-brand-200"
            aria-hidden
          >
            {initials(row)}
          </span>
          <div className="min-w-0 flex-1">
            <p className="flex items-center gap-2 text-sm font-medium text-slate-900 dark:text-slate-100">
              <span className="truncate">{displayName(row)}</span>
              {row.is_premium && (
                <span className="rounded-full bg-amber-100 px-2 py-0.5 text-[10px] font-medium text-amber-800 dark:bg-amber-500/20 dark:text-amber-200">
                  premium
                </span>
              )}
            </p>
            <p className="text-xs text-slate-500 dark:text-slate-400">
              <span className="tabular-nums">tg #{row.telegram_id}</span>
              {row.language_code && <> · {row.language_code.toUpperCase()}</>}
            </p>
          </div>
          <span className="text-xs text-slate-500 dark:text-slate-400">{formatRelative(row.created_at)}</span>
        </li>
      ))}
    </ul>
  );
}
