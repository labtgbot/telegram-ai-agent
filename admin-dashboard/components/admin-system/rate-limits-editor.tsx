"use client";

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";

import { Button } from "@/components/ui/button";
import { putRateLimits } from "@/lib/admin-system/browser";
import type {
  RateLimitPlanMap,
  RateLimitsResponse,
} from "@/lib/admin-system/types";
import { formatDateTime } from "@/lib/dashboard/format";

import {
  ErrorBanner,
  SuccessBanner,
  humanSystemError,
  textareaClass,
} from "./system-shared";

interface RateLimitsEditorProps {
  initial: RateLimitsResponse;
  canEdit: boolean;
}

function stringifyOverrides(overrides: RateLimitPlanMap): string {
  if (!overrides || Object.keys(overrides).length === 0) return "{}";
  return JSON.stringify(overrides, null, 2);
}

function parseOverrides(raw: string): RateLimitPlanMap | string {
  const trimmed = raw.trim();
  if (!trimmed) return {};
  let parsed: unknown;
  try {
    parsed = JSON.parse(trimmed);
  } catch (err) {
    return `Invalid JSON: ${(err as Error).message}`;
  }
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    return "Overrides must be an object mapping plan → { action: { limit, window_seconds } }.";
  }
  const out: RateLimitPlanMap = {};
  for (const [plan, rules] of Object.entries(parsed as Record<string, unknown>)) {
    if (!rules || typeof rules !== "object" || Array.isArray(rules)) {
      return `Plan "${plan}" must map to an object of rules.`;
    }
    const planMap: Record<string, { limit: number; window_seconds: number }> = {};
    for (const [action, rule] of Object.entries(rules as Record<string, unknown>)) {
      if (!rule || typeof rule !== "object" || Array.isArray(rule)) {
        return `Rule "${plan}.${action}" must be an object with limit and window_seconds.`;
      }
      const rec = rule as Record<string, unknown>;
      const limit = typeof rec.limit === "number" ? rec.limit : Number(rec.limit);
      const window = typeof rec.window_seconds === "number" ? rec.window_seconds : Number(rec.window_seconds);
      if (!Number.isFinite(limit) || limit <= 0 || !Number.isInteger(limit)) {
        return `Rule "${plan}.${action}".limit must be a positive integer.`;
      }
      if (!Number.isFinite(window) || window <= 0 || !Number.isInteger(window)) {
        return `Rule "${plan}.${action}".window_seconds must be a positive integer.`;
      }
      planMap[action] = { limit, window_seconds: window };
    }
    out[plan] = planMap;
  }
  return out;
}

export function RateLimitsEditor({ initial, canEdit }: RateLimitsEditorProps) {
  const router = useRouter();
  const [draft, setDraft] = useState<string>(() => stringifyOverrides(initial.overrides));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | undefined>();
  const [success, setSuccess] = useState<string | undefined>();

  const defaultsJson = useMemo(() => JSON.stringify(initial.defaults, null, 2), [initial.defaults]);
  const plansJson = useMemo(() => JSON.stringify(initial.plans, null, 2), [initial.plans]);

  async function submit() {
    if (!canEdit) return;
    const parsed = parseOverrides(draft);
    if (typeof parsed === "string") {
      setError(parsed);
      return;
    }
    setBusy(true);
    setError(undefined);
    try {
      const response = await putRateLimits({ overrides: parsed });
      setDraft(stringifyOverrides(response.overrides));
      setSuccess("Rate-limit overrides saved.");
      router.refresh();
    } catch (err) {
      setError(humanSystemError(err, "Failed to save rate limits."));
    } finally {
      setBusy(false);
    }
  }

  async function clearOverrides() {
    if (!canEdit) return;
    if (!window.confirm("Drop all overrides and fall back to defaults?")) return;
    setBusy(true);
    setError(undefined);
    try {
      const response = await putRateLimits({ overrides: null });
      setDraft(stringifyOverrides(response.overrides));
      setSuccess("Overrides cleared — defaults active.");
      router.refresh();
    } catch (err) {
      setError(humanSystemError(err, "Failed to clear overrides."));
    } finally {
      setBusy(false);
    }
  }

  const disabled = !canEdit || busy;

  return (
    <section
      aria-label="Rate limits"
      className="space-y-4 rounded-card border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900"
    >
      <header>
        <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-100">Rate limits</h2>
        <p className="text-sm text-slate-500 dark:text-slate-400">
          Per-plan token-bucket limits. Overrides merge on top of defaults; missing plans inherit
          defaults. Super-admin only.
        </p>
      </header>

      <ErrorBanner>{error}</ErrorBanner>
      <SuccessBanner>{success}</SuccessBanner>

      <div className="grid gap-4 lg:grid-cols-2">
        <div className="space-y-2">
          <p className="text-xs font-medium text-slate-600 dark:text-slate-300">
            Overrides (JSON)
          </p>
          <textarea
            rows={14}
            value={draft}
            onChange={(e) => {
              setDraft(e.target.value);
              setError(undefined);
              setSuccess(undefined);
            }}
            disabled={disabled}
            className={textareaClass}
            spellCheck={false}
          />
          <p className="text-[11px] text-slate-500 dark:text-slate-400">
            Example:{" "}
            <code className="text-xs">
              {`{ "free": { "messages": { "limit": 30, "window_seconds": 60 } } }`}
            </code>
          </p>
        </div>
        <div className="space-y-2">
          <p className="text-xs font-medium text-slate-600 dark:text-slate-300">Defaults (read-only)</p>
          <pre className="max-h-48 overflow-auto rounded-md border border-slate-200 bg-slate-50 p-3 text-xs text-slate-700 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-300">
            {defaultsJson}
          </pre>
          <p className="text-xs font-medium text-slate-600 dark:text-slate-300">
            Merged (effective)
          </p>
          <pre className="max-h-48 overflow-auto rounded-md border border-slate-200 bg-slate-50 p-3 text-xs text-slate-700 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-300">
            {plansJson}
          </pre>
        </div>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-2 border-t border-slate-200 pt-3 dark:border-slate-800">
        <p className="text-xs text-slate-500 dark:text-slate-400">
          {initial.updated_at
            ? `Last changed ${formatDateTime(initial.updated_at)} by admin #${initial.updated_by ?? "?"}.`
            : "Never changed."}
        </p>
        <div className="flex gap-2">
          <Button variant="ghost" size="md" onClick={clearOverrides} disabled={disabled}>
            Clear overrides
          </Button>
          <Button variant="primary" size="md" onClick={submit} disabled={disabled}>
            {busy ? "Saving…" : "Save overrides"}
          </Button>
        </div>
      </div>
    </section>
  );
}
