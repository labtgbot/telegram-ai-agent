"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { postCancelBroadcast } from "@/lib/admin-broadcasts/browser";
import {
  CANCELLABLE_STATUSES,
  type BroadcastListResponse,
  type BroadcastResponse,
  type BroadcastStatus,
} from "@/lib/admin-broadcasts/types";
import { isApiError } from "@/lib/api/errors";
import { formatDateTime, formatInteger } from "@/lib/dashboard/format";
import { cn } from "@/lib/utils";

interface BroadcastsListProps {
  page: BroadcastListResponse;
  canCancel: boolean;
}

const STATUS_LABEL: Record<BroadcastStatus, string> = {
  draft: "Draft",
  scheduled: "Scheduled",
  in_progress: "In progress",
  completed: "Completed",
  cancelled: "Cancelled",
  failed: "Failed",
};

const STATUS_CLASS: Record<BroadcastStatus, string> = {
  draft: "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300",
  scheduled: "bg-amber-100 text-amber-800 dark:bg-amber-500/20 dark:text-amber-200",
  in_progress: "bg-sky-100 text-sky-800 dark:bg-sky-500/20 dark:text-sky-200",
  completed: "bg-emerald-100 text-emerald-800 dark:bg-emerald-500/20 dark:text-emerald-200",
  cancelled: "bg-slate-200 text-slate-700 dark:bg-slate-700 dark:text-slate-200",
  failed: "bg-rose-100 text-rose-800 dark:bg-rose-500/20 dark:text-rose-200",
};

function humanError(err: unknown): string {
  if (isApiError(err)) {
    if (err.status === 403) return "You don't have permission to cancel this broadcast.";
    if (err.status === 401) return "Your session expired — please log in again.";
    if (err.status === 404) return "Broadcast not found.";
    if (err.status === 409) {
      const payload = err.payload as { detail?: unknown } | undefined;
      if (typeof payload?.detail === "string") return payload.detail;
      return "Broadcast can no longer be cancelled.";
    }
    return err.message || `Request failed (${err.status}).`;
  }
  if (err instanceof Error) return err.message;
  return "Failed to cancel broadcast.";
}

export function BroadcastsList({ page, canCancel }: BroadcastsListProps) {
  const router = useRouter();
  const [busyId, setBusyId] = useState<number | null>(null);
  const [error, setError] = useState<string | undefined>();

  async function handleCancel(broadcast: BroadcastResponse) {
    setError(undefined);
    if (!window.confirm(`Cancel broadcast #${broadcast.id}? This cannot be undone.`)) return;
    setBusyId(broadcast.id);
    try {
      await postCancelBroadcast(broadcast.id);
      router.refresh();
    } catch (err) {
      setError(humanError(err));
    } finally {
      setBusyId(null);
    }
  }

  return (
    <section aria-label="Broadcast history" className="space-y-3">
      <header className="flex items-baseline justify-between gap-2">
        <div>
          <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-100">Broadcasts</h2>
          <p className="text-sm text-slate-500 dark:text-slate-400">
            {page.total === 0
              ? "No broadcasts yet."
              : `${formatInteger(page.total)} total — newest first.`}
          </p>
        </div>
      </header>

      {error && (
        <p
          role="alert"
          className="rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700 dark:border-rose-700/40 dark:bg-rose-900/30 dark:text-rose-200"
        >
          {error}
        </p>
      )}

      {page.items.length === 0 ? (
        <p className="rounded-md border border-dashed border-slate-200 px-4 py-8 text-center text-sm text-slate-500 dark:border-slate-700 dark:text-slate-400">
          Nothing to show yet — compose your first broadcast above.
        </p>
      ) : (
        <div className="overflow-x-auto rounded-md border border-slate-200 dark:border-slate-800">
          <table className="min-w-full divide-y divide-slate-200 text-sm dark:divide-slate-800">
            <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500 dark:bg-slate-900/40 dark:text-slate-400">
              <tr>
                <th scope="col" className="px-4 py-3 text-left font-semibold">
                  Campaign
                </th>
                <th scope="col" className="px-4 py-3 text-left font-semibold">
                  Status
                </th>
                <th scope="col" className="px-4 py-3 text-left font-semibold">
                  Audience
                </th>
                <th scope="col" className="px-4 py-3 text-right font-semibold">
                  Delivery
                </th>
                <th scope="col" className="px-4 py-3 text-left font-semibold">
                  Schedule
                </th>
                <th scope="col" className="px-4 py-3 text-right font-semibold">
                  Actions
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
              {page.items.map((broadcast) => {
                const cancellable = canCancel && CANCELLABLE_STATUSES.has(broadcast.status);
                const isBusy = busyId === broadcast.id;
                const total = broadcast.total_recipients || 0;
                const sent = broadcast.sent_count || 0;
                const delivered = broadcast.delivered_count || 0;
                const failed = broadcast.failed_count || 0;
                const skipped = broadcast.skipped_count || 0;
                const progressPct = total > 0 ? Math.min(100, Math.round((sent / total) * 100)) : 0;
                return (
                  <tr key={broadcast.id} className="bg-white dark:bg-slate-900">
                    <td className="px-4 py-3 align-top">
                      <p className="font-medium text-slate-900 dark:text-slate-100">
                        {broadcast.title || `Broadcast #${broadcast.id}`}
                      </p>
                      <p className="mt-1 line-clamp-2 max-w-md text-xs text-slate-500 dark:text-slate-400">
                        {broadcast.text}
                      </p>
                      <p className="mt-1 text-[11px] text-slate-400">
                        #{broadcast.id} · created {formatDateTime(broadcast.created_at)} by admin #
                        {broadcast.created_by}
                      </p>
                      {broadcast.last_error && (
                        <p className="mt-1 text-[11px] text-rose-600 dark:text-rose-300">
                          Last error: {broadcast.last_error}
                        </p>
                      )}
                    </td>
                    <td className="px-4 py-3 align-top">
                      <span
                        className={cn(
                          "inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium",
                          STATUS_CLASS[broadcast.status],
                        )}
                      >
                        {STATUS_LABEL[broadcast.status]}
                      </span>
                    </td>
                    <td className="px-4 py-3 align-top text-xs text-slate-600 dark:text-slate-300">
                      <code className="rounded bg-slate-100 px-1 py-0.5 dark:bg-slate-800">
                        {broadcast.audience}
                      </code>
                      {broadcast.audience === "custom" &&
                        broadcast.audience_filter &&
                        Array.isArray(
                          (broadcast.audience_filter as { telegram_ids?: unknown }).telegram_ids,
                        ) && (
                          <p className="mt-1">
                            {
                              (broadcast.audience_filter as { telegram_ids: unknown[] })
                                .telegram_ids.length
                            }{" "}
                            ID(s)
                          </p>
                        )}
                    </td>
                    <td className="px-4 py-3 align-top text-right">
                      <p className="font-mono text-xs text-slate-700 dark:text-slate-200">
                        {formatInteger(sent)}/{formatInteger(total)}
                      </p>
                      <div className="mt-1 h-1.5 w-24 overflow-hidden rounded-full bg-slate-200 dark:bg-slate-700">
                        <div
                          className="h-full bg-brand-600"
                          style={{ width: `${progressPct}%` }}
                          aria-hidden
                        />
                      </div>
                      <p className="mt-1 text-[11px] text-slate-500 dark:text-slate-400">
                        ✓ {formatInteger(delivered)} · ✗ {formatInteger(failed)} · –{" "}
                        {formatInteger(skipped)}
                      </p>
                    </td>
                    <td className="px-4 py-3 align-top text-xs text-slate-600 dark:text-slate-300">
                      {broadcast.scheduled_at ? (
                        <>
                          <p>Scheduled</p>
                          <p className="text-[11px] text-slate-500 dark:text-slate-400">
                            {formatDateTime(broadcast.scheduled_at)}
                          </p>
                        </>
                      ) : (
                        <p>Immediate</p>
                      )}
                      {broadcast.started_at && (
                        <p className="mt-1 text-[11px] text-slate-400">
                          started {formatDateTime(broadcast.started_at)}
                        </p>
                      )}
                      {broadcast.finished_at && (
                        <p className="text-[11px] text-slate-400">
                          finished {formatDateTime(broadcast.finished_at)}
                        </p>
                      )}
                    </td>
                    <td className="px-4 py-3 align-top text-right">
                      {cancellable ? (
                        <Button
                          variant="destructive"
                          size="sm"
                          onClick={() => handleCancel(broadcast)}
                          disabled={isBusy}
                          type="button"
                        >
                          {isBusy ? "Cancelling…" : "Cancel"}
                        </Button>
                      ) : (
                        <span className="text-xs text-slate-400">—</span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {page.has_more && (
        <p className="text-xs text-slate-500 dark:text-slate-400">
          Showing the first {page.items.length} of {formatInteger(page.total)}. Pagination controls
          will land in a follow-up.
        </p>
      )}
    </section>
  );
}
