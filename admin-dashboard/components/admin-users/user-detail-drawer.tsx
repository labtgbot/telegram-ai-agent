"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  addTokens,
  banUser,
  getUserStats,
  sendUserMessage,
  unbanUser,
} from "@/lib/admin-users/browser";
import type { UserStatsResponse } from "@/lib/admin-users/types";
import { isApiError } from "@/lib/api/errors";
import {
  formatDateTime,
  formatInteger,
  formatRelative,
} from "@/lib/dashboard/format";
import { cn } from "@/lib/utils";

interface UserDetailDrawerProps {
  /** When undefined the drawer is closed. */
  userId: number | undefined;
}

interface DrawerState {
  loading: boolean;
  data: UserStatsResponse | undefined;
  error: string | undefined;
}

export function UserDetailDrawer({ userId }: UserDetailDrawerProps) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [state, setState] = useState<DrawerState>({
    loading: false,
    data: undefined,
    error: undefined,
  });
  const [busyAction, setBusyAction] = useState<string | undefined>();

  const reload = useCallback(async () => {
    if (!userId) return;
    setState((prev) => ({ ...prev, loading: true, error: undefined }));
    try {
      const data = await getUserStats(userId);
      setState({ loading: false, data, error: undefined });
    } catch (err) {
      setState({ loading: false, data: undefined, error: humanError(err) });
    }
  }, [userId]);

  useEffect(() => {
    if (!userId) {
      setState({ loading: false, data: undefined, error: undefined });
      return;
    }
    void reload();
  }, [reload, userId]);

  const closeDrawer = useCallback(() => {
    const params = new URLSearchParams(searchParams?.toString() ?? "");
    params.delete("user");
    const qs = params.toString();
    router.push(qs ? `/users?${qs}` : "/users");
  }, [router, searchParams]);

  // Close on Escape for keyboard users.
  useEffect(() => {
    if (!userId) return;
    function handleKey(event: KeyboardEvent) {
      if (event.key === "Escape") closeDrawer();
    }
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [closeDrawer, userId]);

  const runAction = useCallback(
    async (label: string, op: () => Promise<unknown>) => {
      setBusyAction(label);
      try {
        await op();
        await reload();
        return true;
      } catch (err) {
        setState((prev) => ({ ...prev, error: humanError(err) }));
        return false;
      } finally {
        setBusyAction(undefined);
      }
    },
    [reload],
  );

  if (!userId) return null;

  return (
    <div className="fixed inset-0 z-40 flex" role="dialog" aria-modal aria-label="User details">
      <button
        type="button"
        aria-label="Close drawer"
        onClick={closeDrawer}
        className="flex-1 bg-slate-900/40 backdrop-blur-sm dark:bg-slate-950/60"
      />
      <aside className="flex h-full w-full max-w-xl flex-col overflow-y-auto border-l border-slate-200 bg-white p-6 shadow-xl dark:border-slate-800 dark:bg-slate-950">
        <header className="flex items-start justify-between gap-3">
          <div>
            <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-100">
              User #{userId}
            </h2>
            <p className="text-xs text-slate-500 dark:text-slate-400">
              Admin actions are recorded in the audit log.
            </p>
          </div>
          <Button variant="ghost" size="sm" onClick={closeDrawer}>
            Close
          </Button>
        </header>

        {state.loading && !state.data && (
          <p className="mt-6 text-sm text-slate-500 dark:text-slate-400">Loading…</p>
        )}
        {state.error && (
          <p className="mt-4 rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700 dark:border-rose-700/40 dark:bg-rose-900/30 dark:text-rose-200">
            {state.error}
          </p>
        )}

        {state.data && (
          <UserSections
            stats={state.data}
            busyAction={busyAction}
            onAddTokens={(amount, reason) =>
              runAction("add-tokens", () => addTokens(userId, { amount, reason }))
            }
            onBan={(reason) => runAction("ban", () => banUser(userId, { reason }))}
            onUnban={() => runAction("unban", () => unbanUser(userId))}
            onSendMessage={(text) =>
              runAction("message", () => sendUserMessage(userId, { text }))
            }
          />
        )}
      </aside>
    </div>
  );
}

interface UserSectionsProps {
  stats: UserStatsResponse;
  busyAction: string | undefined;
  onAddTokens: (amount: number, reason: string) => Promise<boolean>;
  onBan: (reason: string) => Promise<boolean>;
  onUnban: () => Promise<boolean>;
  onSendMessage: (text: string) => Promise<boolean>;
}

function UserSections({
  stats,
  busyAction,
  onAddTokens,
  onBan,
  onUnban,
  onSendMessage,
}: UserSectionsProps) {
  const user = stats.user;

  return (
    <div className="mt-4 space-y-6">
      <section aria-label="Profile" className="space-y-3">
        <h3 className="text-sm font-semibold text-slate-700 dark:text-slate-200">Profile</h3>
        <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
          <Detail label="Name" value={fullName(user)} />
          <Detail label="Username" value={user.username ? `@${user.username}` : "—"} />
          <Detail label="Telegram ID" value={String(user.telegram_id)} />
          <Detail label="Role" value={user.role} />
          <Detail
            label="Premium"
            value={user.is_premium ? "yes" : "no"}
            tone={user.is_premium ? "good" : undefined}
          />
          <Detail
            label="Banned"
            value={user.is_banned ? "yes" : "no"}
            tone={user.is_banned ? "bad" : undefined}
          />
          <Detail label="Token balance" value={formatInteger(user.token_balance)} />
          <Detail label="Total spent" value={formatInteger(user.total_tokens_spent)} />
          <Detail
            label="Joined"
            value={user.created_at ? formatDateTime(user.created_at) : "—"}
          />
          <Detail
            label="Last active"
            value={user.last_active_at ? formatRelative(user.last_active_at) : "—"}
          />
          {user.is_banned && user.ban_reason && (
            <Detail label="Ban reason" value={user.ban_reason} className="col-span-2" />
          )}
        </dl>
      </section>

      <section aria-label="Recent transactions" className="space-y-2">
        <h3 className="text-sm font-semibold text-slate-700 dark:text-slate-200">
          Transactions{" "}
          <span className="text-xs font-normal text-slate-400">
            ({stats.transactions_total} total)
          </span>
        </h3>
        {stats.recent_transactions.length === 0 ? (
          <p className="text-sm text-slate-500 dark:text-slate-400">No transactions yet.</p>
        ) : (
          <ul className="divide-y divide-slate-200 text-sm dark:divide-slate-800">
            {stats.recent_transactions.map((tx) => (
              <li key={tx.id} className="flex items-center justify-between gap-2 py-2">
                <div className="min-w-0">
                  <p className="font-medium text-slate-800 dark:text-slate-100">
                    {tx.transaction_type}
                  </p>
                  <p className="text-xs text-slate-500 dark:text-slate-400">
                    {tx.package_name ?? tx.payment_status ?? "—"} ·{" "}
                    {formatRelative(tx.completed_at ?? tx.created_at)}
                  </p>
                </div>
                <div className="text-right text-sm tabular-nums">
                  <p className="font-semibold text-slate-800 dark:text-slate-100">
                    {tx.tokens_amount > 0 ? "+" : ""}
                    {formatInteger(tx.tokens_amount)}
                  </p>
                  {tx.stars_amount != null && (
                    <p className="text-xs text-amber-700 dark:text-amber-300">
                      {formatInteger(tx.stars_amount)} ⭐
                    </p>
                  )}
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section aria-label="Services usage" className="space-y-2">
        <h3 className="text-sm font-semibold text-slate-700 dark:text-slate-200">
          Services usage
        </h3>
        {stats.services_usage.length === 0 ? (
          <p className="text-sm text-slate-500 dark:text-slate-400">No usage logged.</p>
        ) : (
          <ul className="divide-y divide-slate-200 text-sm dark:divide-slate-800">
            {stats.services_usage.map((row) => (
              <li key={row.service_type} className="flex items-center justify-between py-2">
                <p className="text-slate-700 dark:text-slate-200">{row.service_type}</p>
                <p className="text-right text-xs text-slate-500 dark:text-slate-400">
                  <span className="tabular-nums">{formatInteger(row.requests)}</span> req ·{" "}
                  <span className="tabular-nums">{formatInteger(row.tokens_spent)}</span> tokens
                </p>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section aria-label="Referrals" className="space-y-2">
        <h3 className="text-sm font-semibold text-slate-700 dark:text-slate-200">
          Referrals{" "}
          <span className="text-xs font-normal text-slate-400">
            ({stats.referrals_count} total)
          </span>
        </h3>
        {stats.recent_referrals.length === 0 ? (
          <p className="text-sm text-slate-500 dark:text-slate-400">No referrals yet.</p>
        ) : (
          <ul className="divide-y divide-slate-200 text-sm dark:divide-slate-800">
            {stats.recent_referrals.map((row) => (
              <li key={row.user_id} className="flex items-center justify-between py-2">
                <div>
                  <p className="font-medium text-slate-800 dark:text-slate-100">
                    {row.username ? `@${row.username}` : row.first_name ?? `user #${row.user_id}`}
                  </p>
                  <p className="text-xs text-slate-500 dark:text-slate-400">
                    tg #{row.telegram_id} · joined {formatRelative(row.created_at)}
                  </p>
                </div>
                {row.is_premium && (
                  <span className="rounded-full bg-amber-100 px-2 py-0.5 text-[10px] font-medium text-amber-800 dark:bg-amber-500/20 dark:text-amber-200">
                    premium
                  </span>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>

      <section aria-label="Admin actions" className="space-y-4">
        <h3 className="text-sm font-semibold text-slate-700 dark:text-slate-200">
          Admin actions
        </h3>
        <AddTokensForm onSubmit={onAddTokens} disabled={busyAction !== undefined} />
        <BanControls
          banned={user.is_banned}
          onBan={onBan}
          onUnban={onUnban}
          disabled={busyAction !== undefined}
        />
        <SendMessageForm onSubmit={onSendMessage} disabled={busyAction !== undefined} />
      </section>
    </div>
  );
}

function fullName(user: { first_name: string | null; last_name: string | null }): string {
  const parts = [user.first_name, user.last_name].filter(Boolean) as string[];
  return parts.length ? parts.join(" ") : "—";
}

function Detail({
  label,
  value,
  tone,
  className,
}: {
  label: string;
  value: string;
  tone?: "good" | "bad";
  className?: string;
}) {
  return (
    <div className={cn("space-y-0.5", className)}>
      <dt className="text-xs uppercase tracking-wide text-slate-500 dark:text-slate-400">{label}</dt>
      <dd
        className={cn(
          "font-medium text-slate-900 dark:text-slate-100",
          tone === "good" && "text-emerald-600 dark:text-emerald-300",
          tone === "bad" && "text-rose-600 dark:text-rose-300",
        )}
      >
        {value}
      </dd>
    </div>
  );
}

function AddTokensForm({
  onSubmit,
  disabled,
}: {
  onSubmit: (amount: number, reason: string) => Promise<boolean>;
  disabled: boolean;
}) {
  const [amount, setAmount] = useState("");
  const [reason, setReason] = useState("manual grant");
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<string | undefined>();

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const parsed = Number.parseInt(amount, 10);
    if (!Number.isFinite(parsed) || parsed <= 0) {
      setStatus("Amount must be a positive integer.");
      return;
    }
    setBusy(true);
    setStatus(undefined);
    const ok = await onSubmit(parsed, reason.trim() || "manual grant");
    setBusy(false);
    if (ok) {
      setAmount("");
      setStatus(`Credited ${parsed} tokens.`);
    }
  }

  return (
    <form
      onSubmit={submit}
      className="rounded-md border border-slate-200 p-3 dark:border-slate-800"
      aria-label="Add tokens"
    >
      <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
        Add tokens
      </p>
      <div className="flex flex-col gap-2 sm:flex-row">
        <Input
          inputMode="numeric"
          placeholder="Amount"
          value={amount}
          onChange={(e) => setAmount(e.target.value)}
          disabled={disabled || busy}
          aria-label="Amount"
        />
        <Input
          placeholder="Reason"
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          disabled={disabled || busy}
          aria-label="Reason"
        />
        <Button type="submit" variant="primary" size="md" disabled={disabled || busy}>
          {busy ? "Crediting…" : "Credit"}
        </Button>
      </div>
      {status && <p className="mt-2 text-xs text-slate-500 dark:text-slate-400">{status}</p>}
    </form>
  );
}

function BanControls({
  banned,
  onBan,
  onUnban,
  disabled,
}: {
  banned: boolean;
  onBan: (reason: string) => Promise<boolean>;
  onUnban: () => Promise<boolean>;
  disabled: boolean;
}) {
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);

  async function handleBan(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    await onBan(reason.trim());
    setBusy(false);
    setReason("");
  }

  async function handleUnban() {
    setBusy(true);
    await onUnban();
    setBusy(false);
  }

  if (banned) {
    return (
      <div className="rounded-md border border-rose-200 bg-rose-50 p-3 dark:border-rose-700/40 dark:bg-rose-900/20">
        <p className="text-xs font-semibold uppercase tracking-wide text-rose-700 dark:text-rose-200">
          Banned
        </p>
        <Button
          variant="secondary"
          size="md"
          onClick={handleUnban}
          disabled={disabled || busy}
          className="mt-2"
        >
          {busy ? "Lifting…" : "Lift ban"}
        </Button>
      </div>
    );
  }

  return (
    <form
      onSubmit={handleBan}
      className="rounded-md border border-slate-200 p-3 dark:border-slate-800"
      aria-label="Ban user"
    >
      <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
        Ban user
      </p>
      <div className="flex flex-col gap-2 sm:flex-row">
        <Input
          placeholder="Reason (optional)"
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          disabled={disabled || busy}
          aria-label="Ban reason"
        />
        <Button type="submit" variant="destructive" size="md" disabled={disabled || busy}>
          {busy ? "Banning…" : "Ban"}
        </Button>
      </div>
    </form>
  );
}

function SendMessageForm({
  onSubmit,
  disabled,
}: {
  onSubmit: (text: string) => Promise<boolean>;
  disabled: boolean;
}) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<string | undefined>();

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!text.trim()) {
      setStatus("Message text is required.");
      return;
    }
    setBusy(true);
    setStatus(undefined);
    const ok = await onSubmit(text.trim());
    setBusy(false);
    if (ok) {
      setText("");
      setStatus("Message delivered.");
    }
  }

  return (
    <form
      onSubmit={submit}
      className="rounded-md border border-slate-200 p-3 dark:border-slate-800"
      aria-label="Send Telegram message"
    >
      <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
        Send Telegram message
      </p>
      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        rows={3}
        placeholder="Hi! …"
        disabled={disabled || busy}
        aria-label="Message text"
        className={cn(
          "w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900",
          "shadow-sm focus-visible:outline focus-visible:outline-2 focus-visible:outline-brand-500",
          "dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100",
        )}
      />
      <div className="mt-2 flex items-center justify-between gap-2">
        <p className="text-xs text-slate-500 dark:text-slate-400">{status}</p>
        <Button type="submit" variant="primary" size="md" disabled={disabled || busy}>
          {busy ? "Sending…" : "Send"}
        </Button>
      </div>
    </form>
  );
}

function humanError(err: unknown): string {
  if (isApiError(err)) {
    if (err.status === 403) return "You don't have permission for this action.";
    if (err.status === 404) return "User not found.";
    if (err.status === 422) return err.message || "Validation failed.";
    if (err.status === 502) return "Telegram could not deliver the message.";
    return err.message || `Request failed (${err.status}).`;
  }
  if (err instanceof Error) return err.message;
  return "Unexpected error.";
}

