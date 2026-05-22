"use client";

import { useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { getPricingHistory, postPricingUpdate } from "@/lib/admin-pricing/browser";
import type {
  PricingConfig,
  PricingHistoryItem,
  PricingHistoryResponse,
  PricingPackageUpdate,
  PricingUpdatePayload,
} from "@/lib/admin-pricing/types";
import { isApiError } from "@/lib/api/errors";
import { formatDateTime, formatInteger } from "@/lib/dashboard/format";
import { cn } from "@/lib/utils";

interface PricingEditorProps {
  initialConfig: PricingConfig;
  initialHistory: PricingHistoryResponse;
  /** When false, inputs are disabled and the save bar is hidden. */
  canEdit: boolean;
}

interface PackageDraft {
  tokens: string;
  stars: string;
  discount: string;
}

interface DraftState {
  packages: Record<string, PackageDraft>;
  global_discount: string;
  seasonal_promo: string;
  first_purchase_bonus: string;
  referral_bonus: string;
  daily_bonus: string;
  currency_rate: string;
}

function configToDraft(config: PricingConfig): DraftState {
  const packages: Record<string, PackageDraft> = {};
  for (const pkg of config.packages) {
    packages[pkg.code] = {
      tokens: String(pkg.tokens),
      stars: String(pkg.stars),
      discount: String(pkg.discount),
    };
  }
  return {
    packages,
    global_discount: String(config.global_discount),
    seasonal_promo: String(config.seasonal_promo),
    first_purchase_bonus: String(config.first_purchase_bonus),
    referral_bonus: String(config.referral_bonus),
    daily_bonus: String(config.daily_bonus),
    currency_rate: String(config.currency_rate),
  };
}

function clampPercent(value: number, max: number): number {
  if (!Number.isFinite(value)) return 0;
  return Math.min(Math.max(0, Math.trunc(value)), max);
}

function computeEffectiveStars(
  base_stars: number,
  base_discount: number,
  globalPct: number,
  seasonalPct: number,
  maxDiscount: number,
): number {
  const combined = clampPercent(base_discount + globalPct + seasonalPct, maxDiscount);
  const effective = Math.trunc((base_stars * (100 - combined)) / 100);
  return Math.max(1, effective);
}

function parsePositiveInt(value: string): number | null {
  const trimmed = value.trim();
  if (!trimmed) return null;
  if (!/^\d+$/.test(trimmed)) return null;
  const parsed = Number.parseInt(trimmed, 10);
  if (!Number.isFinite(parsed)) return null;
  return parsed;
}

function parsePositiveFloat(value: string): number | null {
  const trimmed = value.trim();
  if (!trimmed) return null;
  if (!/^\d+(\.\d+)?$/.test(trimmed)) return null;
  const parsed = Number.parseFloat(trimmed);
  if (!Number.isFinite(parsed)) return null;
  return parsed;
}

interface DiffEntry {
  label: string;
  before: string;
  after: string;
}

function buildDiff(
  config: PricingConfig,
  draft: DraftState,
): {
  payload: PricingUpdatePayload;
  entries: DiffEntry[];
  errors: string[];
} {
  const errors: string[] = [];
  const entries: DiffEntry[] = [];
  const packagePayload: Record<string, PricingPackageUpdate> = {};

  for (const pkg of config.packages) {
    const draftPkg = draft.packages[pkg.code];
    if (!draftPkg) continue;
    const update: PricingPackageUpdate = {};
    const tokens = parsePositiveInt(draftPkg.tokens);
    const stars = parsePositiveInt(draftPkg.stars);
    const discount = parsePositiveInt(draftPkg.discount);

    if (tokens === null || tokens < 1) {
      errors.push(`${pkg.title}: tokens must be a positive integer.`);
    } else if (tokens > config.limits.max_tokens_per_package) {
      errors.push(
        `${pkg.title}: tokens cannot exceed ${formatInteger(config.limits.max_tokens_per_package)}.`,
      );
    } else if (tokens !== pkg.tokens) {
      update.tokens = tokens;
      entries.push({
        label: `${pkg.title} · tokens`,
        before: formatInteger(pkg.tokens),
        after: formatInteger(tokens),
      });
    }

    if (stars === null || stars < 1) {
      errors.push(`${pkg.title}: stars must be a positive integer.`);
    } else if (stars > config.limits.max_stars_per_package) {
      errors.push(
        `${pkg.title}: stars cannot exceed ${formatInteger(config.limits.max_stars_per_package)}.`,
      );
    } else if (stars !== pkg.stars) {
      update.stars = stars;
      entries.push({
        label: `${pkg.title} · stars`,
        before: `${formatInteger(pkg.stars)} ⭐`,
        after: `${formatInteger(stars)} ⭐`,
      });
    }

    if (discount === null) {
      errors.push(`${pkg.title}: discount must be 0–${config.limits.max_discount_percent}%.`);
    } else if (discount > config.limits.max_discount_percent) {
      errors.push(`${pkg.title}: discount cannot exceed ${config.limits.max_discount_percent}%.`);
    } else if (discount !== pkg.discount) {
      update.discount = discount;
      entries.push({
        label: `${pkg.title} · discount`,
        before: `${pkg.discount}%`,
        after: `${discount}%`,
      });
    }

    if (Object.keys(update).length > 0) {
      packagePayload[pkg.code] = update;
    }
  }

  const payload: PricingUpdatePayload = {};
  if (Object.keys(packagePayload).length > 0) {
    payload.packages = packagePayload;
  }

  const globalScalars: Array<{
    key: keyof Omit<PricingUpdatePayload, "packages">;
    label: string;
    max: number;
    unit?: string;
    value: number;
    draftStr: string;
  }> = [
    {
      key: "global_discount",
      label: "Global discount",
      max: config.limits.max_discount_percent,
      unit: "%",
      value: config.global_discount,
      draftStr: draft.global_discount,
    },
    {
      key: "seasonal_promo",
      label: "Seasonal promo",
      max: config.limits.max_discount_percent,
      unit: "%",
      value: config.seasonal_promo,
      draftStr: draft.seasonal_promo,
    },
    {
      key: "first_purchase_bonus",
      label: "First-purchase bonus",
      max: config.limits.max_discount_percent,
      unit: "%",
      value: config.first_purchase_bonus,
      draftStr: draft.first_purchase_bonus,
    },
    {
      key: "referral_bonus",
      label: "Referral bonus",
      max: config.limits.max_bonus_tokens,
      unit: " tokens",
      value: config.referral_bonus,
      draftStr: draft.referral_bonus,
    },
    {
      key: "daily_bonus",
      label: "Daily bonus",
      max: config.limits.max_bonus_tokens,
      unit: " tokens",
      value: config.daily_bonus,
      draftStr: draft.daily_bonus,
    },
  ];

  for (const item of globalScalars) {
    const parsed = parsePositiveInt(item.draftStr);
    if (parsed === null) {
      errors.push(`${item.label}: must be a non-negative integer.`);
      continue;
    }
    if (parsed > item.max) {
      errors.push(`${item.label}: cannot exceed ${formatInteger(item.max)}${item.unit ?? ""}.`);
      continue;
    }
    if (parsed !== item.value) {
      (payload as Record<string, unknown>)[item.key] = parsed;
      entries.push({
        label: item.label,
        before: `${formatInteger(item.value)}${item.unit ?? ""}`,
        after: `${formatInteger(parsed)}${item.unit ?? ""}`,
      });
    }
  }

  const currencyRate = parsePositiveFloat(draft.currency_rate);
  if (currencyRate === null) {
    errors.push("Currency rate: must be a non-negative number.");
  } else if (currencyRate > 1000) {
    errors.push("Currency rate: cannot exceed 1000.");
  } else if (currencyRate !== config.currency_rate) {
    payload.currency_rate = currencyRate;
    entries.push({
      label: "Currency rate (Stars → USD)",
      before: config.currency_rate.toString(),
      after: currencyRate.toString(),
    });
  }

  return { payload, entries, errors };
}

export function PricingEditor({ initialConfig, initialHistory, canEdit }: PricingEditorProps) {
  const [config, setConfig] = useState<PricingConfig>(initialConfig);
  const [draft, setDraft] = useState<DraftState>(() => configToDraft(initialConfig));
  const [history, setHistory] = useState<PricingHistoryResponse>(initialHistory);
  const [error, setError] = useState<string | undefined>();
  const [success, setSuccess] = useState<string | undefined>();
  const [busy, setBusy] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);

  const diff = useMemo(() => buildDiff(config, draft), [config, draft]);
  const dirty = diff.entries.length > 0;

  function resetDraft() {
    setDraft(configToDraft(config));
    setError(undefined);
    setSuccess(undefined);
  }

  function openConfirm() {
    setError(undefined);
    setSuccess(undefined);
    if (diff.errors.length > 0) {
      setError(diff.errors[0]);
      return;
    }
    if (!dirty) {
      setError("No changes to save.");
      return;
    }
    setConfirmOpen(true);
  }

  async function submit() {
    setBusy(true);
    setError(undefined);
    try {
      const response = await postPricingUpdate(diff.payload);
      setConfig(response.config);
      setDraft(configToDraft(response.config));
      setConfirmOpen(false);
      setSuccess(`Saved — audit log #${response.audit_log_id}.`);
      try {
        const refreshed = await getPricingHistory(1, history.limit);
        setHistory(refreshed);
      } catch {
        // history refresh is best-effort
      }
    } catch (err) {
      setError(humanError(err));
    } finally {
      setBusy(false);
    }
  }

  function updatePackageField(code: string, field: keyof PackageDraft, value: string) {
    setDraft((prev) => {
      const current = prev.packages[code] ?? { tokens: "", stars: "", discount: "" };
      return {
        ...prev,
        packages: {
          ...prev.packages,
          [code]: { ...current, [field]: value },
        },
      };
    });
  }

  function updateScalar(field: keyof Omit<DraftState, "packages">, value: string) {
    setDraft((prev) => ({ ...prev, [field]: value }));
  }

  const globalPct = parsePositiveInt(draft.global_discount) ?? 0;
  const seasonalPct = parsePositiveInt(draft.seasonal_promo) ?? 0;

  return (
    <div className="space-y-6">
      {error && (
        <p
          role="alert"
          className="rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700 dark:border-rose-700/40 dark:bg-rose-900/30 dark:text-rose-200"
        >
          {error}
        </p>
      )}
      {success && (
        <p
          role="status"
          className="rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-700 dark:border-emerald-700/40 dark:bg-emerald-900/30 dark:text-emerald-200"
        >
          {success}
        </p>
      )}

      <section aria-label="Package overrides" className="space-y-3">
        <header>
          <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-100">Packages</h2>
          <p className="text-sm text-slate-500 dark:text-slate-400">
            Per-package overrides apply on top of the global modifiers. Saved changes affect new
            invoices immediately; in-flight invoices keep the price quoted at checkout, and active
            subscriptions renew at their locked plan price.
          </p>
        </header>
        <div className="grid gap-4 lg:grid-cols-2">
          {config.packages.map((pkg) => {
            const draftPkg = draft.packages[pkg.code];
            if (!draftPkg) return null;
            const pkgDiscount = parsePositiveInt(draftPkg.discount) ?? pkg.discount;
            const pkgStars = parsePositiveInt(draftPkg.stars) ?? pkg.stars;
            const effective = computeEffectiveStars(
              pkgStars,
              pkgDiscount,
              globalPct,
              seasonalPct,
              config.limits.max_discount_percent,
            );
            return (
              <article
                key={pkg.code}
                className={cn(
                  "rounded-card border border-slate-200 bg-white p-4 shadow-sm",
                  "dark:border-slate-800 dark:bg-slate-900",
                )}
              >
                <div className="flex items-baseline justify-between gap-2">
                  <div>
                    <h3 className="text-sm font-semibold text-slate-900 dark:text-slate-100">
                      {pkg.title}
                    </h3>
                    <p className="text-xs text-slate-500 dark:text-slate-400">
                      {pkg.description}{" "}
                      {pkg.is_subscription && (
                        <span className="ml-1 rounded-full bg-amber-100 px-2 py-0.5 text-[10px] font-medium text-amber-800 dark:bg-amber-500/20 dark:text-amber-200">
                          subscription
                        </span>
                      )}
                    </p>
                  </div>
                  <code className="text-[11px] text-slate-400">{pkg.code}</code>
                </div>
                <div className="mt-3 grid grid-cols-3 gap-2">
                  <NumberField
                    label="Tokens"
                    value={draftPkg.tokens}
                    onChange={(v) => updatePackageField(pkg.code, "tokens", v)}
                    disabled={!canEdit || busy}
                    max={config.limits.max_tokens_per_package}
                  />
                  <NumberField
                    label="Stars"
                    value={draftPkg.stars}
                    onChange={(v) => updatePackageField(pkg.code, "stars", v)}
                    disabled={!canEdit || busy}
                    max={config.limits.max_stars_per_package}
                  />
                  <NumberField
                    label={`Discount % (≤${config.limits.max_discount_percent})`}
                    value={draftPkg.discount}
                    onChange={(v) => updatePackageField(pkg.code, "discount", v)}
                    disabled={!canEdit || busy}
                    max={config.limits.max_discount_percent}
                  />
                </div>
                <p className="mt-2 text-xs text-slate-500 dark:text-slate-400">
                  Effective price after all modifiers:{" "}
                  <strong className="text-slate-700 dark:text-slate-200">
                    {formatInteger(effective)} ⭐
                  </strong>{" "}
                  (≈ ${(effective * config.currency_rate).toFixed(2)})
                </p>
              </article>
            );
          })}
        </div>
      </section>

      <section aria-label="Global modifiers" className="space-y-3">
        <header>
          <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-100">
            Global modifiers
          </h2>
          <p className="text-sm text-slate-500 dark:text-slate-400">
            Combined discount (per-package + global + seasonal) is capped at{" "}
            {config.limits.max_discount_percent}%.
          </p>
        </header>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          <NumberField
            label="Global discount %"
            value={draft.global_discount}
            onChange={(v) => updateScalar("global_discount", v)}
            disabled={!canEdit || busy}
            max={config.limits.max_discount_percent}
          />
          <NumberField
            label="Seasonal promo %"
            value={draft.seasonal_promo}
            onChange={(v) => updateScalar("seasonal_promo", v)}
            disabled={!canEdit || busy}
            max={config.limits.max_discount_percent}
          />
          <NumberField
            label="First-purchase bonus %"
            value={draft.first_purchase_bonus}
            onChange={(v) => updateScalar("first_purchase_bonus", v)}
            disabled={!canEdit || busy}
            max={config.limits.max_discount_percent}
          />
          <NumberField
            label="Referral bonus (tokens)"
            value={draft.referral_bonus}
            onChange={(v) => updateScalar("referral_bonus", v)}
            disabled={!canEdit || busy}
            max={config.limits.max_bonus_tokens}
          />
          <NumberField
            label="Daily bonus (tokens)"
            value={draft.daily_bonus}
            onChange={(v) => updateScalar("daily_bonus", v)}
            disabled={!canEdit || busy}
            max={config.limits.max_bonus_tokens}
          />
          <NumberField
            label="Currency rate (Stars → USD)"
            value={draft.currency_rate}
            onChange={(v) => updateScalar("currency_rate", v)}
            disabled={!canEdit || busy}
            allowDecimal
          />
        </div>
      </section>

      {canEdit && (
        <div className="sticky bottom-4 z-20 flex items-center justify-between gap-3 rounded-card border border-slate-200 bg-white p-3 shadow-lg dark:border-slate-800 dark:bg-slate-900">
          <p className="text-sm text-slate-600 dark:text-slate-300">
            {dirty
              ? `${diff.entries.length} pending change${diff.entries.length === 1 ? "" : "s"}.`
              : "No pending changes."}
          </p>
          <div className="flex gap-2">
            <Button variant="ghost" size="md" onClick={resetDraft} disabled={!dirty || busy}>
              Discard
            </Button>
            <Button
              variant="primary"
              size="md"
              onClick={openConfirm}
              disabled={!dirty || busy || diff.errors.length > 0}
            >
              Save changes…
            </Button>
          </div>
        </div>
      )}

      {confirmOpen && (
        <ConfirmDialog
          entries={diff.entries}
          busy={busy}
          onCancel={() => setConfirmOpen(false)}
          onConfirm={submit}
        />
      )}

      <HistorySection history={history} />
    </div>
  );
}

interface NumberFieldProps {
  label: string;
  value: string;
  onChange: (value: string) => void;
  disabled: boolean;
  max?: number;
  allowDecimal?: boolean;
}

function NumberField({ label, value, onChange, disabled, max, allowDecimal }: NumberFieldProps) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-xs font-medium text-slate-600 dark:text-slate-300">{label}</span>
      <Input
        inputMode={allowDecimal ? "decimal" : "numeric"}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        disabled={disabled}
        max={max}
      />
    </label>
  );
}

interface ConfirmDialogProps {
  entries: DiffEntry[];
  busy: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}

function ConfirmDialog({ entries, busy, onCancel, onConfirm }: ConfirmDialogProps) {
  return (
    <div
      role="dialog"
      aria-modal
      aria-label="Confirm pricing changes"
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4 backdrop-blur-sm dark:bg-slate-950/60"
    >
      <div className="w-full max-w-md rounded-card border border-slate-200 bg-white p-5 shadow-xl dark:border-slate-800 dark:bg-slate-900">
        <h2 className="text-base font-semibold text-slate-900 dark:text-slate-100">
          Apply pricing changes?
        </h2>
        <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
          New invoices will use the new prices immediately. Existing pending invoices keep the price
          quoted at checkout, and active subscriptions renew at their locked plan price.
        </p>
        <ul className="mt-3 max-h-64 space-y-1 overflow-y-auto rounded-md border border-slate-200 bg-slate-50 p-3 text-xs dark:border-slate-700 dark:bg-slate-950">
          {entries.map((entry) => (
            <li key={entry.label} className="flex flex-col">
              <span className="font-medium text-slate-700 dark:text-slate-200">{entry.label}</span>
              <span className="text-slate-500 dark:text-slate-400">
                <code className="rounded bg-white px-1 py-0.5 dark:bg-slate-800">
                  {entry.before}
                </code>{" "}
                →{" "}
                <code className="rounded bg-emerald-50 px-1 py-0.5 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-200">
                  {entry.after}
                </code>
              </span>
            </li>
          ))}
        </ul>
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="ghost" size="md" onClick={onCancel} disabled={busy}>
            Cancel
          </Button>
          <Button variant="primary" size="md" onClick={onConfirm} disabled={busy}>
            {busy ? "Saving…" : "Apply changes"}
          </Button>
        </div>
      </div>
    </div>
  );
}

function HistorySection({ history }: { history: PricingHistoryResponse }) {
  return (
    <section aria-label="Change history" className="space-y-3">
      <header>
        <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-100">Change history</h2>
        <p className="text-sm text-slate-500 dark:text-slate-400">
          {history.total === 0
            ? "No changes recorded yet."
            : `${formatInteger(history.total)} change${history.total === 1 ? "" : "s"} recorded — newest first.`}
        </p>
      </header>
      {history.items.length > 0 && (
        <ol className="space-y-2">
          {history.items.map((item) => (
            <HistoryRow key={item.id} item={item} />
          ))}
        </ol>
      )}
    </section>
  );
}

function HistoryRow({ item }: { item: PricingHistoryItem }) {
  const summary = useMemo(() => summariseDiff(item.diff), [item.diff]);
  return (
    <li className="rounded-md border border-slate-200 bg-white p-3 shadow-sm dark:border-slate-800 dark:bg-slate-900">
      <div className="flex items-center justify-between gap-2 text-xs">
        <p className="font-medium text-slate-700 dark:text-slate-200">
          Admin #{item.admin_id} · {formatDateTime(item.created_at)}
        </p>
        {item.ip_address && <code className="text-slate-400">{item.ip_address}</code>}
      </div>
      {summary.length === 0 ? (
        <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
          No structured diff recorded.
        </p>
      ) : (
        <ul className="mt-2 space-y-0.5 text-xs text-slate-600 dark:text-slate-300">
          {summary.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
      )}
    </li>
  );
}

function summariseDiff(diff: Record<string, unknown> | null): string[] {
  if (!diff || typeof diff !== "object") return [];
  const lines: string[] = [];
  const globals = diff.globals;
  if (globals && typeof globals === "object") {
    for (const [key, change] of Object.entries(globals)) {
      if (change && typeof change === "object" && "before" in change && "after" in change) {
        const c = change as { before: unknown; after: unknown };
        lines.push(`${key}: ${String(c.before)} → ${String(c.after)}`);
      }
    }
  }
  const packages = diff.packages;
  if (packages && typeof packages === "object") {
    for (const [code, change] of Object.entries(packages)) {
      if (!change || typeof change !== "object") continue;
      for (const [field, fieldChange] of Object.entries(change)) {
        if (
          fieldChange &&
          typeof fieldChange === "object" &&
          "before" in fieldChange &&
          "after" in fieldChange
        ) {
          const c = fieldChange as { before: unknown; after: unknown };
          lines.push(`${code}.${field}: ${String(c.before)} → ${String(c.after)}`);
        }
      }
    }
  }
  return lines;
}

function humanError(err: unknown): string {
  if (isApiError(err)) {
    if (err.status === 403) return "You don't have permission to edit pricing.";
    if (err.status === 401) return "Your session expired — please log in again.";
    if (err.status === 404) {
      const payload = err.payload as { detail?: { message?: string } } | undefined;
      return payload?.detail?.message ?? "Unknown package code.";
    }
    if (err.status === 400) {
      const payload = err.payload as { detail?: { message?: string } } | undefined;
      return payload?.detail?.message ?? "Invalid pricing payload.";
    }
    return err.message || `Request failed (${err.status}).`;
  }
  if (err instanceof Error) return err.message;
  return "Failed to save pricing.";
}
