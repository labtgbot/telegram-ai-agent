"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  deleteWelcomeMessage,
  postWelcomeMessage,
  putWelcomeMessage,
} from "@/lib/admin-content/browser";
import type {
  WelcomeMessage,
  WelcomeMessageListResponse,
  WelcomeMessagePayload,
} from "@/lib/admin-content/types";
import { formatDateTime } from "@/lib/dashboard/format";

import {
  ErrorBanner,
  Field,
  SuccessBanner,
  humanContentError,
  selectClass,
  textareaClass,
} from "./content-shared";

interface WelcomesEditorProps {
  initial: WelcomeMessageListResponse;
  canEdit: boolean;
}

interface Draft {
  id: number | null;
  name: string;
  body: string;
  locale: string;
  is_active: boolean;
}

function blankDraft(): Draft {
  return { id: null, name: "", body: "", locale: "en", is_active: false };
}

function draftFromItem(item: WelcomeMessage): Draft {
  return {
    id: item.id,
    name: item.name,
    body: item.body,
    locale: item.locale,
    is_active: item.is_active,
  };
}

function buildPayload(draft: Draft): { payload?: WelcomeMessagePayload; error?: string } {
  const name = draft.name.trim();
  const body = draft.body.trim();
  if (!name) return { error: "Name is required." };
  if (!body) return { error: "Body is required." };
  return {
    payload: {
      name,
      body,
      locale: draft.locale.trim() || "en",
      is_active: draft.is_active,
    },
  };
}

export function WelcomesEditor({ initial, canEdit }: WelcomesEditorProps) {
  const router = useRouter();
  const [draft, setDraft] = useState<Draft>(() => blankDraft());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | undefined>();
  const [success, setSuccess] = useState<string | undefined>();

  function patch(update: Partial<Draft>) {
    setDraft((prev) => ({ ...prev, ...update }));
    setError(undefined);
    setSuccess(undefined);
  }

  async function submit() {
    if (!canEdit) return;
    const { payload, error: validationError } = buildPayload(draft);
    if (!payload) {
      setError(validationError);
      return;
    }
    setBusy(true);
    setError(undefined);
    try {
      if (draft.id === null) {
        const created = await postWelcomeMessage(payload);
        setSuccess(`Created welcome "${created.name}".`);
      } else {
        const updated = await putWelcomeMessage(draft.id, payload);
        setSuccess(`Saved changes to "${updated.name}".`);
      }
      setDraft(blankDraft());
      router.refresh();
    } catch (err) {
      setError(humanContentError(err, "Failed to save welcome message."));
    } finally {
      setBusy(false);
    }
  }

  async function handleDelete(item: WelcomeMessage) {
    if (!canEdit) return;
    if (!window.confirm(`Delete welcome "${item.name}"? This cannot be undone.`)) return;
    setBusy(true);
    setError(undefined);
    try {
      await deleteWelcomeMessage(item.id);
      setSuccess(`Deleted "${item.name}".`);
      if (draft.id === item.id) setDraft(blankDraft());
      router.refresh();
    } catch (err) {
      setError(humanContentError(err, "Failed to delete welcome."));
    } finally {
      setBusy(false);
    }
  }

  const disabled = !canEdit || busy;
  const isEditing = draft.id !== null;

  return (
    <section
      aria-label="Welcome messages"
      className="space-y-4 rounded-card border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900"
    >
      <header className="flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-100">
            Welcome messages
          </h2>
          <p className="text-sm text-slate-500 dark:text-slate-400">
            {initial.total === 0 ? "No welcomes yet." : `${initial.total} total.`} Only one welcome
            can be active per locale — activating a new one deactivates the previous.
          </p>
        </div>
        {isEditing && (
          <Button variant="ghost" size="sm" onClick={() => setDraft(blankDraft())} disabled={busy}>
            Cancel edit
          </Button>
        )}
      </header>

      <ErrorBanner>{error}</ErrorBanner>
      <SuccessBanner>{success}</SuccessBanner>

      <div className="grid gap-3 lg:grid-cols-3">
        <Field label="Name">
          <Input
            value={draft.name}
            onChange={(e) => patch({ name: e.target.value })}
            disabled={disabled}
            placeholder="EN — default"
            maxLength={120}
          />
        </Field>
        <Field label="Locale">
          <Input
            value={draft.locale}
            onChange={(e) => patch({ locale: e.target.value })}
            disabled={disabled}
            placeholder="en"
            maxLength={20}
          />
        </Field>
        <Field label="Status">
          <select
            className={selectClass}
            value={draft.is_active ? "active" : "inactive"}
            onChange={(e) => patch({ is_active: e.target.value === "active" })}
            disabled={disabled}
          >
            <option value="inactive">Inactive</option>
            <option value="active">Active (will deactivate others for this locale)</option>
          </select>
        </Field>
      </div>

      <Field label="Body">
        <textarea
          rows={6}
          value={draft.body}
          onChange={(e) => patch({ body: e.target.value })}
          disabled={disabled}
          className={textareaClass}
          placeholder="Hi! I'm your Telegram AI agent. Send /start to begin."
        />
      </Field>

      <div className="flex justify-end gap-2 border-t border-slate-200 pt-3 dark:border-slate-800">
        <Button variant="ghost" size="md" onClick={() => setDraft(blankDraft())} disabled={busy}>
          Reset
        </Button>
        <Button variant="primary" size="md" onClick={submit} disabled={disabled}>
          {isEditing
            ? busy
              ? "Saving…"
              : "Save changes"
            : busy
              ? "Creating…"
              : "Create welcome"}
        </Button>
      </div>

      <div className="overflow-x-auto rounded-md border border-slate-200 dark:border-slate-800">
        <table className="min-w-full divide-y divide-slate-200 text-sm dark:divide-slate-800">
          <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500 dark:bg-slate-900/40 dark:text-slate-400">
            <tr>
              <th scope="col" className="px-4 py-3 text-left font-semibold">Name / body</th>
              <th scope="col" className="px-4 py-3 text-left font-semibold">Locale</th>
              <th scope="col" className="px-4 py-3 text-left font-semibold">Status</th>
              <th scope="col" className="px-4 py-3 text-left font-semibold">Updated</th>
              <th scope="col" className="px-4 py-3 text-right font-semibold">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
            {initial.items.length === 0 ? (
              <tr>
                <td colSpan={5} className="px-4 py-6 text-center text-sm text-slate-500">
                  No welcomes yet.
                </td>
              </tr>
            ) : (
              initial.items.map((item) => (
                <tr key={item.id} className="bg-white dark:bg-slate-900">
                  <td className="px-4 py-3 align-top">
                    <p className="font-medium text-slate-900 dark:text-slate-100">{item.name}</p>
                    <p className="mt-1 line-clamp-2 max-w-md text-xs text-slate-500 dark:text-slate-400">
                      {item.body}
                    </p>
                  </td>
                  <td className="px-4 py-3 align-top text-xs text-slate-700 dark:text-slate-200">
                    {item.locale}
                  </td>
                  <td className="px-4 py-3 align-top">
                    <span
                      className={
                        item.is_active
                          ? "rounded-full bg-emerald-100 px-2 py-0.5 text-xs font-medium text-emerald-800 dark:bg-emerald-500/20 dark:text-emerald-200"
                          : "rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-700 dark:bg-slate-800 dark:text-slate-300"
                      }
                    >
                      {item.is_active ? "Active" : "Inactive"}
                    </span>
                  </td>
                  <td className="px-4 py-3 align-top text-xs text-slate-500 dark:text-slate-400">
                    {formatDateTime(item.updated_at)}
                  </td>
                  <td className="px-4 py-3 align-top text-right">
                    <div className="flex justify-end gap-2">
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => setDraft(draftFromItem(item))}
                        disabled={!canEdit || busy}
                      >
                        Edit
                      </Button>
                      <Button
                        variant="destructive"
                        size="sm"
                        onClick={() => handleDelete(item)}
                        disabled={!canEdit || busy}
                      >
                        Delete
                      </Button>
                    </div>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}
