"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useCallback } from "react";

import { formatDateTime, formatInteger, formatRelative } from "@/lib/dashboard/format";
import { cn } from "@/lib/utils";
import {
  SORT_FIELDS,
  type AdminUserSummary,
  type SortDirection,
  type SortField,
} from "@/lib/admin-users/types";

interface UsersTableProps {
  rows: AdminUserSummary[];
  sort: SortField;
  direction: SortDirection;
  selectedId?: number;
}

const COLUMNS: Array<{ key: ColumnKey; label: string; align?: "right" }> = [
  { key: "user", label: "User" },
  { key: "telegram_id", label: "Telegram ID", align: "right" },
  { key: "role", label: "Role" },
  { key: "token_balance", label: "Balance", align: "right" },
  { key: "total_tokens_spent", label: "Spent", align: "right" },
  { key: "total_requests", label: "Requests", align: "right" },
  { key: "created_at", label: "Joined" },
  { key: "last_active_at", label: "Last active" },
];

type ColumnKey =
  | "user"
  | "telegram_id"
  | "role"
  | "token_balance"
  | "total_tokens_spent"
  | "total_requests"
  | "created_at"
  | "last_active_at";

const SORTABLE_COLUMNS = new Set<ColumnKey>(SORT_FIELDS as readonly ColumnKey[]);

export function UsersTable({ rows, sort, direction, selectedId }: UsersTableProps) {
  const router = useRouter();
  const searchParams = useSearchParams();

  const navigateSort = useCallback(
    (column: ColumnKey) => {
      if (!SORTABLE_COLUMNS.has(column)) return;
      const params = new URLSearchParams(searchParams?.toString() ?? "");
      const nextDirection: SortDirection =
        column === sort && direction === "desc" ? "asc" : "desc";
      params.set("sort", column);
      params.set("direction", nextDirection);
      params.delete("page");
      const qs = params.toString();
      router.push(qs ? `/users?${qs}` : "/users");
    },
    [direction, router, searchParams, sort],
  );

  const selectRow = useCallback(
    (userId: number) => {
      const params = new URLSearchParams(searchParams?.toString() ?? "");
      params.set("user", String(userId));
      router.push(`/users?${params.toString()}`);
    },
    [router, searchParams],
  );

  if (rows.length === 0) {
    return (
      <p className="rounded-md border border-dashed border-slate-200 px-4 py-8 text-center text-sm text-slate-500 dark:border-slate-700 dark:text-slate-400">
        No users match the current filters.
      </p>
    );
  }

  return (
    <div className="overflow-x-auto rounded-md border border-slate-200 dark:border-slate-800">
      <table className="min-w-full divide-y divide-slate-200 text-sm dark:divide-slate-800">
        <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500 dark:bg-slate-900/40 dark:text-slate-400">
          <tr>
            {COLUMNS.map((col) => {
              const sortable = SORTABLE_COLUMNS.has(col.key);
              const active = sortable && sort === col.key;
              return (
                <th
                  key={col.key}
                  scope="col"
                  className={cn(
                    "whitespace-nowrap px-4 py-3 font-semibold",
                    col.align === "right" ? "text-right" : "text-left",
                  )}
                  aria-sort={
                    active ? (direction === "asc" ? "ascending" : "descending") : undefined
                  }
                >
                  {sortable ? (
                    <button
                      type="button"
                      onClick={() => navigateSort(col.key)}
                      className={cn(
                        "inline-flex items-center gap-1 text-inherit hover:text-slate-900 dark:hover:text-slate-100",
                        active && "text-slate-900 dark:text-slate-100",
                      )}
                    >
                      {col.label}
                      <SortIndicator active={active} direction={direction} />
                    </button>
                  ) : (
                    col.label
                  )}
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-200 bg-white dark:divide-slate-800 dark:bg-slate-950">
          {rows.map((row) => (
            <tr
              key={row.id}
              onClick={() => selectRow(row.id)}
              className={cn(
                "cursor-pointer transition-colors hover:bg-slate-50 dark:hover:bg-slate-900",
                row.id === selectedId && "bg-brand-50/60 dark:bg-brand-900/30",
              )}
            >
              <td className="whitespace-nowrap px-4 py-3">
                <div className="flex items-center gap-2">
                  <span className="font-medium text-slate-900 dark:text-slate-100">
                    {displayName(row)}
                  </span>
                  {row.is_premium && <Badge tone="amber">premium</Badge>}
                  {row.is_banned && <Badge tone="red">banned</Badge>}
                </div>
                <p className="text-xs text-slate-500 dark:text-slate-400">
                  {row.username ? `@${row.username}` : `user #${row.id}`}
                </p>
              </td>
              <td className="whitespace-nowrap px-4 py-3 text-right tabular-nums text-slate-700 dark:text-slate-300">
                {row.telegram_id}
              </td>
              <td className="whitespace-nowrap px-4 py-3 text-slate-600 dark:text-slate-300">
                {row.role}
              </td>
              <td className="whitespace-nowrap px-4 py-3 text-right tabular-nums">
                {formatInteger(row.token_balance)}
              </td>
              <td className="whitespace-nowrap px-4 py-3 text-right tabular-nums text-slate-500 dark:text-slate-400">
                {formatInteger(row.total_tokens_spent)}
              </td>
              <td className="whitespace-nowrap px-4 py-3 text-right tabular-nums text-slate-500 dark:text-slate-400">
                {formatInteger(row.total_requests)}
              </td>
              <td className="whitespace-nowrap px-4 py-3 text-slate-500 dark:text-slate-400">
                {row.created_at ? (
                  <span title={formatDateTime(row.created_at)}>
                    {formatRelative(row.created_at)}
                  </span>
                ) : (
                  "—"
                )}
              </td>
              <td className="whitespace-nowrap px-4 py-3 text-slate-500 dark:text-slate-400">
                {row.last_active_at ? (
                  <span title={formatDateTime(row.last_active_at)}>
                    {formatRelative(row.last_active_at)}
                  </span>
                ) : (
                  "—"
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function displayName(row: AdminUserSummary): string {
  const parts = [row.first_name, row.last_name].filter(Boolean) as string[];
  if (parts.length > 0) return parts.join(" ");
  if (row.username) return `@${row.username}`;
  return `user #${row.id}`;
}

function Badge({
  children,
  tone,
}: {
  children: React.ReactNode;
  tone: "amber" | "red";
}) {
  const palette =
    tone === "amber"
      ? "bg-amber-100 text-amber-800 dark:bg-amber-500/20 dark:text-amber-200"
      : "bg-rose-100 text-rose-700 dark:bg-rose-500/20 dark:text-rose-200";
  return (
    <span className={cn("rounded-full px-2 py-0.5 text-[10px] font-medium", palette)}>
      {children}
    </span>
  );
}

function SortIndicator({
  active,
  direction,
}: {
  active: boolean;
  direction: SortDirection;
}) {
  if (!active) return <span aria-hidden>↕</span>;
  return <span aria-hidden>{direction === "asc" ? "↑" : "↓"}</span>;
}

export interface PaginationProps {
  page: number;
  limit: number;
  total: number;
  hasMore: boolean;
}

export function UsersPagination({ page, limit, total, hasMore }: PaginationProps) {
  const searchParams = useSearchParams();

  function buildHref(targetPage: number): string {
    const params = new URLSearchParams(searchParams?.toString() ?? "");
    if (targetPage <= 1) params.delete("page");
    else params.set("page", String(targetPage));
    const qs = params.toString();
    return qs ? `/users?${qs}` : "/users";
  }

  const start = total === 0 ? 0 : (page - 1) * limit + 1;
  const end = Math.min(total, page * limit);

  return (
    <div className="flex items-center justify-between gap-3 text-sm text-slate-500 dark:text-slate-400">
      <p>
        Showing <strong className="text-slate-700 dark:text-slate-200">{start}–{end}</strong> of{" "}
        <strong className="text-slate-700 dark:text-slate-200">{formatInteger(total)}</strong>
      </p>
      <div className="flex items-center gap-2">
        <PaginationLink href={buildHref(page - 1)} disabled={page <= 1}>
          ← Prev
        </PaginationLink>
        <PaginationLink href={buildHref(page + 1)} disabled={!hasMore}>
          Next →
        </PaginationLink>
      </div>
    </div>
  );
}

function PaginationLink({
  href,
  disabled,
  children,
}: {
  href: string;
  disabled: boolean;
  children: React.ReactNode;
}) {
  if (disabled) {
    return (
      <span
        aria-disabled
        className="inline-flex h-8 cursor-not-allowed items-center rounded-md border border-slate-200 px-3 text-xs text-slate-400 dark:border-slate-800 dark:text-slate-600"
      >
        {children}
      </span>
    );
  }
  return (
    <Link
      href={href}
      className="inline-flex h-8 items-center rounded-md border border-slate-200 px-3 text-xs text-slate-700 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-800"
    >
      {children}
    </Link>
  );
}
