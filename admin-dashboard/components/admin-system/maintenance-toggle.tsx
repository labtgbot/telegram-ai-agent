"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

import { Button } from "@/components/ui/button";
import { putMaintenanceState } from "@/lib/admin-system/browser";
import type { MaintenanceState } from "@/lib/admin-system/types";
import { formatDateTime } from "@/lib/dashboard/format";

import {
  ErrorBanner,
  Field,
  SuccessBanner,
  humanSystemError,
  textareaClass,
} from "./system-shared";

interface MaintenanceToggleProps {
  initial: MaintenanceState;
  canEdit: boolean;
}

export function MaintenanceToggle({ initial, canEdit }: MaintenanceToggleProps) {
  const router = useRouter();
  const [enabled, setEnabled] = useState(initial.enabled);
  const [message, setMessage] = useState(initial.message ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | undefined>();
  const [success, setSuccess] = useState<string | undefined>();

  async function submit(nextEnabled: boolean) {
    if (!canEdit) return;
    setBusy(true);
    setError(undefined);
    setSuccess(undefined);
    try {
      const trimmed = message.trim();
      await putMaintenanceState({
        enabled: nextEnabled,
        message: trimmed ? trimmed : null,
      });
      setEnabled(nextEnabled);
      setSuccess(
        nextEnabled
          ? "Maintenance mode enabled — user-facing endpoints will return 503."
          : "Maintenance mode disabled.",
      );
      router.refresh();
    } catch (err) {
      setError(humanSystemError(err, "Failed to update maintenance mode."));
    } finally {
      setBusy(false);
    }
  }

  const disabled = !canEdit || busy;

  return (
    <section
      aria-label="Maintenance mode"
      className="space-y-4 rounded-card border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900"
    >
      <header className="flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-100">
            Maintenance mode
          </h2>
          <p className="text-sm text-slate-500 dark:text-slate-400">
            When enabled, user-facing endpoints return 503 with the message below. Admin endpoints
            stay accessible.
          </p>
        </div>
        <span
          className={
            enabled
              ? "rounded-full bg-rose-100 px-3 py-1 text-xs font-semibold text-rose-800 dark:bg-rose-500/20 dark:text-rose-200"
              : "rounded-full bg-emerald-100 px-3 py-1 text-xs font-semibold text-emerald-800 dark:bg-emerald-500/20 dark:text-emerald-200"
          }
        >
          {enabled ? "On — site in maintenance" : "Off — site serving traffic"}
        </span>
      </header>

      <ErrorBanner>{error}</ErrorBanner>
      <SuccessBanner>{success}</SuccessBanner>

      <Field label="User-facing message" hint="Shown when maintenance mode is on. Leave blank for default copy.">
        <textarea
          rows={3}
          value={message}
          onChange={(e) => {
            setMessage(e.target.value);
            setSuccess(undefined);
            setError(undefined);
          }}
          disabled={disabled}
          className={textareaClass}
          maxLength={500}
          placeholder="We&apos;re upgrading the bot — back in ~15 minutes."
        />
      </Field>

      <div className="flex flex-wrap items-center justify-between gap-2 border-t border-slate-200 pt-3 dark:border-slate-800">
        <p className="text-xs text-slate-500 dark:text-slate-400">
          {initial.updated_at
            ? `Last changed ${formatDateTime(initial.updated_at)} by admin #${initial.updated_by ?? "?"}.`
            : "Never changed."}
        </p>
        <div className="flex gap-2">
          <Button
            variant="secondary"
            size="md"
            onClick={() => submit(false)}
            disabled={disabled || !enabled}
            type="button"
          >
            {busy ? "Saving…" : "Disable"}
          </Button>
          <Button
            variant="destructive"
            size="md"
            onClick={() => {
              if (window.confirm("Enable maintenance mode? Users will be locked out immediately.")) {
                void submit(true);
              }
            }}
            disabled={disabled || enabled}
            type="button"
          >
            {busy ? "Saving…" : "Enable maintenance"}
          </Button>
        </div>
      </div>
    </section>
  );
}
