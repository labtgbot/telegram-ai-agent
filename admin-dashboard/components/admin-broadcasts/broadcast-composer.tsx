"use client";

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { postBroadcast, postPreviewAudience } from "@/lib/admin-broadcasts/browser";
import {
  BROADCAST_AUDIENCES,
  type BroadcastAudience,
  type BroadcastButtonPayload,
  type BroadcastCreateRequest,
} from "@/lib/admin-broadcasts/types";
import { isApiError } from "@/lib/api/errors";
import { cn } from "@/lib/utils";

const TEXT_MAX = 4096;
const TITLE_MAX = 255;
const BUTTONS_MAX = 6;

const AUDIENCE_LABELS: Record<BroadcastAudience, string> = {
  all: "All users",
  premium: "Premium subscribers",
  free: "Free tier",
  inactive_7d: "Inactive ≥7 days",
  custom: "Custom (by Telegram IDs)",
};

interface ButtonDraft {
  text: string;
  url: string;
  callback_data: string;
}

const emptyButton: ButtonDraft = { text: "", url: "", callback_data: "" };

interface ComposerState {
  title: string;
  text: string;
  parse_mode: "HTML" | "MarkdownV2" | "plain";
  media_type: "" | "photo" | "video";
  media_url: string;
  buttons: ButtonDraft[];
  audience: BroadcastAudience;
  custom_telegram_ids: string;
  scheduled_at: string;
}

function emptyState(): ComposerState {
  return {
    title: "",
    text: "",
    parse_mode: "HTML",
    media_type: "",
    media_url: "",
    buttons: [],
    audience: "all",
    custom_telegram_ids: "",
    scheduled_at: "",
  };
}

function parseTelegramIds(raw: string): number[] | string {
  const tokens = raw
    .split(/[\s,;]+/)
    .map((t) => t.trim())
    .filter(Boolean);
  if (tokens.length === 0) return "At least one Telegram ID is required for custom audience.";
  const ids: number[] = [];
  for (const token of tokens) {
    if (!/^-?\d+$/.test(token)) {
      return `"${token}" is not a valid Telegram ID.`;
    }
    ids.push(Number.parseInt(token, 10));
  }
  return ids;
}

function buildPayload(state: ComposerState): {
  payload?: BroadcastCreateRequest;
  errors: string[];
} {
  const errors: string[] = [];
  const text = state.text.trim();
  if (!text) errors.push("Message text is required.");
  if (text.length > TEXT_MAX) errors.push(`Message text exceeds ${TEXT_MAX} characters.`);
  if (state.title.length > TITLE_MAX) {
    errors.push(`Internal title exceeds ${TITLE_MAX} characters.`);
  }
  if (state.media_type && !state.media_url.trim()) {
    errors.push("Media URL is required when a media type is selected.");
  }

  const buttons: BroadcastButtonPayload[] = [];
  for (const [idx, draft] of state.buttons.entries()) {
    const btnText = draft.text.trim();
    const btnUrl = draft.url.trim();
    const btnCallback = draft.callback_data.trim();
    if (!btnText) {
      errors.push(`Button #${idx + 1}: label is required.`);
      continue;
    }
    if (!btnUrl && !btnCallback) {
      errors.push(`Button #${idx + 1}: URL or callback_data is required.`);
      continue;
    }
    if (btnUrl && btnCallback) {
      errors.push(`Button #${idx + 1}: provide either URL or callback_data, not both.`);
      continue;
    }
    buttons.push({
      text: btnText,
      url: btnUrl || undefined,
      callback_data: btnCallback || undefined,
    });
  }
  if (buttons.length > BUTTONS_MAX) {
    errors.push(`Up to ${BUTTONS_MAX} buttons are allowed.`);
  }

  let audience_filter: Record<string, unknown> | undefined;
  if (state.audience === "custom") {
    const parsed = parseTelegramIds(state.custom_telegram_ids);
    if (typeof parsed === "string") {
      errors.push(parsed);
    } else {
      audience_filter = { telegram_ids: parsed };
    }
  }

  let scheduled_at: string | undefined;
  if (state.scheduled_at.trim()) {
    const dt = new Date(state.scheduled_at);
    if (Number.isNaN(dt.getTime())) {
      errors.push("Scheduled time is not a valid date.");
    } else if (dt.getTime() < Date.now() - 60_000) {
      errors.push("Scheduled time must be in the future.");
    } else {
      scheduled_at = dt.toISOString();
    }
  }

  if (errors.length > 0) return { errors };

  const payload: BroadcastCreateRequest = {
    text,
    title: state.title.trim() || undefined,
    parse_mode: state.parse_mode === "plain" ? null : state.parse_mode,
    media_type: state.media_type || undefined,
    media_url: state.media_url.trim() || undefined,
    buttons: buttons.length > 0 ? buttons : undefined,
    audience: state.audience,
    audience_filter,
    scheduled_at,
  };
  return { payload, errors: [] };
}

function humanError(err: unknown): string {
  if (isApiError(err)) {
    if (err.status === 403) return "You don't have permission to create broadcasts.";
    if (err.status === 401) return "Your session expired — please log in again.";
    if (err.status === 400) {
      const payload = err.payload as { detail?: unknown } | undefined;
      const detail = payload?.detail;
      if (typeof detail === "string") {
        if (detail === "empty_audience") return "Audience is empty — refine the selector.";
        return detail;
      }
      return err.message || "Invalid broadcast payload.";
    }
    return err.message || `Request failed (${err.status}).`;
  }
  if (err instanceof Error) return err.message;
  return "Failed to submit broadcast.";
}

interface BroadcastComposerProps {
  canCreate: boolean;
}

export function BroadcastComposer({ canCreate }: BroadcastComposerProps) {
  const router = useRouter();
  const [state, setState] = useState<ComposerState>(() => emptyState());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | undefined>();
  const [success, setSuccess] = useState<string | undefined>();
  const [preview, setPreview] = useState<{ audience: BroadcastAudience; total: number } | null>(
    null,
  );
  const [confirmOpen, setConfirmOpen] = useState(false);

  const { payload, errors } = useMemo(() => buildPayload(state), [state]);
  const charCount = state.text.length;

  function patch(update: Partial<ComposerState>) {
    setState((prev) => ({ ...prev, ...update }));
    setSuccess(undefined);
    setError(undefined);
    setPreview(null);
  }

  function setButton(idx: number, update: Partial<ButtonDraft>) {
    setState((prev) => {
      const next = [...prev.buttons];
      const current = next[idx] ?? { ...emptyButton };
      next[idx] = { ...current, ...update };
      return { ...prev, buttons: next };
    });
    setSuccess(undefined);
    setError(undefined);
  }

  function addButton() {
    setState((prev) => ({ ...prev, buttons: [...prev.buttons, { ...emptyButton }] }));
  }

  function removeButton(idx: number) {
    setState((prev) => ({
      ...prev,
      buttons: prev.buttons.filter((_, i) => i !== idx),
    }));
  }

  async function runPreview() {
    setError(undefined);
    setSuccess(undefined);
    setBusy(true);
    try {
      const filter =
        state.audience === "custom"
          ? (() => {
              const parsed = parseTelegramIds(state.custom_telegram_ids);
              if (typeof parsed === "string") throw new Error(parsed);
              return { telegram_ids: parsed };
            })()
          : null;
      const res = await postPreviewAudience({
        audience: state.audience,
        audience_filter: filter,
      });
      setPreview(res);
    } catch (err) {
      setError(humanError(err));
    } finally {
      setBusy(false);
    }
  }

  function openConfirm() {
    setError(undefined);
    setSuccess(undefined);
    if (errors.length > 0) {
      setError(errors[0]);
      return;
    }
    if (!payload) {
      setError("Fill in the message before submitting.");
      return;
    }
    setConfirmOpen(true);
  }

  async function submit() {
    if (!payload) return;
    setBusy(true);
    setError(undefined);
    try {
      const created = await postBroadcast(payload);
      setSuccess(
        created.status === "scheduled"
          ? `Broadcast #${created.id} scheduled for ${formatLocal(created.scheduled_at)}.`
          : `Broadcast #${created.id} queued (${created.total_recipients} recipients).`,
      );
      setConfirmOpen(false);
      setState(emptyState());
      setPreview(null);
      router.refresh();
    } catch (err) {
      setError(humanError(err));
    } finally {
      setBusy(false);
    }
  }

  const disabled = !canCreate || busy;

  return (
    <section
      aria-label="Compose broadcast"
      className="space-y-4 rounded-card border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900"
    >
      <header>
        <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-100">New broadcast</h2>
        <p className="text-sm text-slate-500 dark:text-slate-400">
          Compose a campaign, preview the audience, optionally schedule, then queue it for the
          delivery worker (respects Telegram&apos;s 30 msg/sec ceiling).
        </p>
      </header>

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

      <div className="grid gap-4 lg:grid-cols-2">
        <div className="space-y-3">
          <Field label="Internal title (optional)">
            <Input
              value={state.title}
              onChange={(e) => patch({ title: e.target.value })}
              disabled={disabled}
              maxLength={TITLE_MAX}
              placeholder="Weekend promo"
            />
          </Field>

          <Field
            label={`Message text (${charCount}/${TEXT_MAX})`}
            hint="Supports the parse-mode selected on the right. Telegram will reject malformed HTML/Markdown."
          >
            <textarea
              value={state.text}
              onChange={(e) => patch({ text: e.target.value })}
              disabled={disabled}
              maxLength={TEXT_MAX + 200}
              rows={8}
              className={cn(
                "w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900 shadow-sm",
                "placeholder:text-slate-400 focus-visible:outline focus-visible:outline-2 focus-visible:outline-brand-500",
                "disabled:cursor-not-allowed disabled:opacity-60",
                "dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100 dark:placeholder:text-slate-500",
                charCount > TEXT_MAX && "border-rose-400 dark:border-rose-500",
              )}
              placeholder="Hello — we just shipped…"
            />
          </Field>

          <div className="grid grid-cols-2 gap-3">
            <Field label="Parse mode">
              <select
                value={state.parse_mode}
                onChange={(e) =>
                  patch({ parse_mode: e.target.value as ComposerState["parse_mode"] })
                }
                disabled={disabled}
                className={selectClass}
              >
                <option value="HTML">HTML</option>
                <option value="MarkdownV2">MarkdownV2</option>
                <option value="plain">Plain text</option>
              </select>
            </Field>
            <Field label="Schedule for (local time)">
              <Input
                type="datetime-local"
                value={state.scheduled_at}
                onChange={(e) => patch({ scheduled_at: e.target.value })}
                disabled={disabled}
              />
            </Field>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <Field label="Media type">
              <select
                value={state.media_type}
                onChange={(e) =>
                  patch({ media_type: e.target.value as ComposerState["media_type"] })
                }
                disabled={disabled}
                className={selectClass}
              >
                <option value="">— none —</option>
                <option value="photo">Photo</option>
                <option value="video">Video</option>
              </select>
            </Field>
            <Field label="Media URL">
              <Input
                value={state.media_url}
                onChange={(e) => patch({ media_url: e.target.value })}
                disabled={disabled || !state.media_type}
                placeholder="https://…"
              />
            </Field>
          </div>
        </div>

        <div className="space-y-3">
          <Field label="Audience">
            <select
              value={state.audience}
              onChange={(e) => patch({ audience: e.target.value as BroadcastAudience })}
              disabled={disabled}
              className={selectClass}
            >
              {BROADCAST_AUDIENCES.map((aud) => (
                <option key={aud} value={aud}>
                  {AUDIENCE_LABELS[aud]}
                </option>
              ))}
            </select>
          </Field>

          {state.audience === "custom" && (
            <Field
              label="Telegram IDs (comma- or newline-separated)"
              hint="Service skips IDs that are not in the users table."
            >
              <textarea
                value={state.custom_telegram_ids}
                onChange={(e) => patch({ custom_telegram_ids: e.target.value })}
                disabled={disabled}
                rows={4}
                className={cn(
                  "w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900 shadow-sm",
                  "focus-visible:outline focus-visible:outline-2 focus-visible:outline-brand-500",
                  "disabled:cursor-not-allowed disabled:opacity-60",
                  "dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100",
                )}
                placeholder="123456789, 987654321"
              />
            </Field>
          )}

          <div className="flex flex-wrap items-center gap-2">
            <Button
              variant="secondary"
              size="sm"
              onClick={runPreview}
              disabled={disabled}
              type="button"
            >
              {busy ? "Counting…" : "Preview audience"}
            </Button>
            {preview && (
              <span className="text-sm text-slate-600 dark:text-slate-300">
                <strong className="text-slate-900 dark:text-slate-100">
                  {preview.total.toLocaleString("en-US")}
                </strong>{" "}
                recipient{preview.total === 1 ? "" : "s"} match{" "}
                <code className="text-xs text-slate-500">{preview.audience}</code>.
              </span>
            )}
          </div>

          <div className="space-y-2 rounded-md border border-slate-200 bg-slate-50/50 p-3 dark:border-slate-700 dark:bg-slate-950/40">
            <div className="flex items-center justify-between">
              <p className="text-sm font-medium text-slate-700 dark:text-slate-200">
                Inline buttons ({state.buttons.length}/{BUTTONS_MAX})
              </p>
              <Button
                variant="ghost"
                size="sm"
                onClick={addButton}
                disabled={disabled || state.buttons.length >= BUTTONS_MAX}
                type="button"
              >
                + Add button
              </Button>
            </div>
            {state.buttons.length === 0 && (
              <p className="text-xs text-slate-500 dark:text-slate-400">
                No buttons. Add up to {BUTTONS_MAX} inline buttons (URL or callback_data).
              </p>
            )}
            {state.buttons.map((btn, idx) => (
              <div
                key={idx}
                className="grid grid-cols-1 gap-2 rounded-md border border-slate-200 bg-white p-2 sm:grid-cols-[1fr_1.5fr_1.5fr_auto] dark:border-slate-700 dark:bg-slate-900"
              >
                <Input
                  value={btn.text}
                  onChange={(e) => setButton(idx, { text: e.target.value })}
                  disabled={disabled}
                  placeholder="Label"
                />
                <Input
                  value={btn.url}
                  onChange={(e) => setButton(idx, { url: e.target.value })}
                  disabled={disabled}
                  placeholder="https://…"
                />
                <Input
                  value={btn.callback_data}
                  onChange={(e) => setButton(idx, { callback_data: e.target.value })}
                  disabled={disabled}
                  placeholder="callback_data"
                />
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => removeButton(idx)}
                  disabled={disabled}
                  type="button"
                  aria-label={`Remove button ${idx + 1}`}
                >
                  ✕
                </Button>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="flex flex-wrap items-center justify-end gap-2 border-t border-slate-200 pt-4 dark:border-slate-800">
        <p className="mr-auto text-xs text-slate-500 dark:text-slate-400">
          {state.scheduled_at
            ? "Scheduled — will run at the chosen time."
            : "Immediate — worker picks it up on its next pass."}
        </p>
        <Button
          variant="ghost"
          size="md"
          onClick={() => {
            setState(emptyState());
            setPreview(null);
            setError(undefined);
            setSuccess(undefined);
          }}
          disabled={busy}
          type="button"
        >
          Reset
        </Button>
        <Button
          variant="primary"
          size="md"
          onClick={openConfirm}
          disabled={disabled || errors.length > 0 || !payload}
          type="button"
        >
          {state.scheduled_at ? "Schedule broadcast…" : "Send broadcast…"}
        </Button>
      </div>

      {confirmOpen && payload && (
        <ConfirmDialog
          payload={payload}
          previewTotal={preview?.audience === payload.audience ? preview.total : null}
          busy={busy}
          onCancel={() => setConfirmOpen(false)}
          onConfirm={submit}
        />
      )}
    </section>
  );
}

const selectClass = cn(
  "h-10 w-full rounded-md border border-slate-200 bg-white px-3 text-sm text-slate-900 shadow-sm",
  "focus-visible:outline focus-visible:outline-2 focus-visible:outline-brand-500",
  "disabled:cursor-not-allowed disabled:opacity-60",
  "dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100",
);

interface FieldProps {
  label: string;
  hint?: string;
  children: React.ReactNode;
}

function Field({ label, hint, children }: FieldProps) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-xs font-medium text-slate-600 dark:text-slate-300">{label}</span>
      {children}
      {hint && <span className="text-[11px] text-slate-500 dark:text-slate-400">{hint}</span>}
    </label>
  );
}

interface ConfirmDialogProps {
  payload: BroadcastCreateRequest;
  previewTotal: number | null;
  busy: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}

function ConfirmDialog({ payload, previewTotal, busy, onCancel, onConfirm }: ConfirmDialogProps) {
  const isScheduled = !!payload.scheduled_at;
  return (
    <div
      role="dialog"
      aria-modal
      aria-label="Confirm broadcast"
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4 backdrop-blur-sm dark:bg-slate-950/60"
    >
      <div className="w-full max-w-lg rounded-card border border-slate-200 bg-white p-5 shadow-xl dark:border-slate-800 dark:bg-slate-900">
        <h2 className="text-base font-semibold text-slate-900 dark:text-slate-100">
          {isScheduled ? "Schedule this broadcast?" : "Send this broadcast?"}
        </h2>
        <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
          {isScheduled
            ? `It will be queued and start at ${formatLocal(payload.scheduled_at)} (local).`
            : "It will be queued for the next worker pass and delivered respecting the 30 msg/sec ceiling."}
          {previewTotal !== null && (
            <>
              {" "}
              <strong className="text-slate-700 dark:text-slate-200">
                {previewTotal.toLocaleString("en-US")}
              </strong>{" "}
              recipient{previewTotal === 1 ? "" : "s"} match the audience.
            </>
          )}
        </p>
        <dl className="mt-3 space-y-1 rounded-md border border-slate-200 bg-slate-50 p-3 text-xs dark:border-slate-700 dark:bg-slate-950">
          <Row label="Audience" value={payload.audience} />
          {payload.title && <Row label="Title" value={payload.title} />}
          <Row label="Parse mode" value={payload.parse_mode ?? "plain"} />
          {payload.media_type && (
            <Row label="Media" value={`${payload.media_type}: ${payload.media_url}`} />
          )}
          {payload.buttons && payload.buttons.length > 0 && (
            <Row
              label="Buttons"
              value={payload.buttons
                .map((b) => `${b.text}${b.url ? " → URL" : " → callback"}`)
                .join(", ")}
            />
          )}
          {payload.scheduled_at && (
            <Row label="Scheduled" value={formatLocal(payload.scheduled_at)} />
          )}
        </dl>
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="ghost" size="md" onClick={onCancel} disabled={busy} type="button">
            Cancel
          </Button>
          <Button variant="primary" size="md" onClick={onConfirm} disabled={busy} type="button">
            {busy ? "Submitting…" : isScheduled ? "Schedule" : "Send"}
          </Button>
        </div>
      </div>
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-3">
      <dt className="text-slate-500 dark:text-slate-400">{label}</dt>
      <dd className="truncate text-right text-slate-700 dark:text-slate-200">{value}</dd>
    </div>
  );
}

function formatLocal(iso: string | null | undefined): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString("en-US", {
      month: "short",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}
