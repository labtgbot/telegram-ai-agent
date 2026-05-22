"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  deletePromptTemplate,
  postPromptTemplate,
  putPromptTemplate,
} from "@/lib/admin-content/browser";
import type {
  PromptTemplate,
  PromptTemplateListResponse,
  PromptTemplatePayload,
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

interface PromptTemplatesEditorProps {
  initial: PromptTemplateListResponse;
  canEdit: boolean;
}

interface Draft {
  id: number | null;
  code: string;
  title: string;
  body: string;
  category: string;
  locale: string;
  sort_order: number;
  is_active: boolean;
}

function blankDraft(): Draft {
  return {
    id: null,
    code: "",
    title: "",
    body: "",
    category: "",
    locale: "en",
    sort_order: 0,
    is_active: true,
  };
}

function draftFromTemplate(t: PromptTemplate): Draft {
  return {
    id: t.id,
    code: t.code,
    title: t.title,
    body: t.body,
    category: t.category ?? "",
    locale: t.locale,
    sort_order: t.sort_order,
    is_active: t.is_active,
  };
}

function buildPayload(draft: Draft): { payload?: PromptTemplatePayload; error?: string } {
  const code = draft.code.trim();
  const title = draft.title.trim();
  const body = draft.body.trim();
  if (!code) return { error: "Code is required." };
  if (!/^[a-z0-9._-]+$/i.test(code)) {
    return { error: "Code must contain only letters, digits, '.', '_', '-'." };
  }
  if (!title) return { error: "Title is required." };
  if (!body) return { error: "Body is required." };
  return {
    payload: {
      code,
      title,
      body,
      category: draft.category.trim() || null,
      locale: draft.locale.trim() || "en",
      sort_order: Number.isFinite(draft.sort_order) ? draft.sort_order : 0,
      is_active: draft.is_active,
    },
  };
}

export function PromptTemplatesEditor({ initial, canEdit }: PromptTemplatesEditorProps) {
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
        const created = await postPromptTemplate(payload);
        setSuccess(`Created prompt template #${created.id} (${created.code}).`);
      } else {
        const updated = await putPromptTemplate(draft.id, payload);
        setSuccess(`Saved changes to #${updated.id} (${updated.code}).`);
      }
      setDraft(blankDraft());
      router.refresh();
    } catch (err) {
      setError(humanContentError(err, "Failed to save prompt template."));
    } finally {
      setBusy(false);
    }
  }

  async function handleDelete(item: PromptTemplate) {
    if (!canEdit) return;
    if (!window.confirm(`Delete prompt template "${item.code}"? This cannot be undone.`)) return;
    setBusy(true);
    setError(undefined);
    try {
      await deletePromptTemplate(item.id);
      setSuccess(`Deleted "${item.code}".`);
      if (draft.id === item.id) setDraft(blankDraft());
      router.refresh();
    } catch (err) {
      setError(humanContentError(err, "Failed to delete template."));
    } finally {
      setBusy(false);
    }
  }

  const disabled = !canEdit || busy;
  const isEditing = draft.id !== null;

  return (
    <section
      aria-label="Prompt templates"
      className="space-y-4 rounded-card border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900"
    >
      <header className="flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-100">
            Prompt templates
          </h2>
          <p className="text-sm text-slate-500 dark:text-slate-400">
            {initial.total === 0
              ? "No templates yet — create your first below."
              : `${initial.total} templates registered.`}
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

      <div className="grid gap-3 lg:grid-cols-2">
        <Field label="Code (machine identifier)" hint="Lowercase letters, digits, '.', '_', '-'.">
          <Input
            value={draft.code}
            onChange={(e) => patch({ code: e.target.value })}
            disabled={disabled || isEditing}
            placeholder="welcome.morning"
            maxLength={100}
          />
        </Field>
        <Field label="Title (human readable)">
          <Input
            value={draft.title}
            onChange={(e) => patch({ title: e.target.value })}
            disabled={disabled}
            placeholder="Morning welcome"
            maxLength={255}
          />
        </Field>
      </div>

      <Field label="Body" hint="Markdown / Telegram-flavoured HTML supported.">
        <textarea
          rows={6}
          value={draft.body}
          onChange={(e) => patch({ body: e.target.value })}
          disabled={disabled}
          className={textareaClass}
          placeholder="Good morning! Today we're looking at…"
        />
      </Field>

      <div className="grid gap-3 lg:grid-cols-4">
        <Field label="Category">
          <Input
            value={draft.category}
            onChange={(e) => patch({ category: e.target.value })}
            disabled={disabled}
            placeholder="onboarding"
            maxLength={80}
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
        <Field label="Sort order">
          <Input
            type="number"
            value={String(draft.sort_order)}
            onChange={(e) => patch({ sort_order: Number.parseInt(e.target.value, 10) || 0 })}
            disabled={disabled}
          />
        </Field>
        <Field label="Status">
          <select
            className={selectClass}
            value={draft.is_active ? "active" : "inactive"}
            onChange={(e) => patch({ is_active: e.target.value === "active" })}
            disabled={disabled}
          >
            <option value="active">Active</option>
            <option value="inactive">Inactive</option>
          </select>
        </Field>
      </div>

      <div className="flex justify-end gap-2 border-t border-slate-200 pt-3 dark:border-slate-800">
        <Button variant="ghost" size="md" onClick={() => setDraft(blankDraft())} disabled={busy}>
          Reset
        </Button>
        <Button variant="primary" size="md" onClick={submit} disabled={disabled}>
          {isEditing ? (busy ? "Saving…" : "Save changes") : busy ? "Creating…" : "Create template"}
        </Button>
      </div>

      <div className="overflow-x-auto rounded-md border border-slate-200 dark:border-slate-800">
        <table className="min-w-full divide-y divide-slate-200 text-sm dark:divide-slate-800">
          <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500 dark:bg-slate-900/40 dark:text-slate-400">
            <tr>
              <th scope="col" className="px-4 py-3 text-left font-semibold">Code / title</th>
              <th scope="col" className="px-4 py-3 text-left font-semibold">Locale</th>
              <th scope="col" className="px-4 py-3 text-left font-semibold">Category</th>
              <th scope="col" className="px-4 py-3 text-left font-semibold">Status</th>
              <th scope="col" className="px-4 py-3 text-left font-semibold">Updated</th>
              <th scope="col" className="px-4 py-3 text-right font-semibold">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
            {initial.items.length === 0 ? (
              <tr>
                <td colSpan={6} className="px-4 py-6 text-center text-sm text-slate-500">
                  No templates yet.
                </td>
              </tr>
            ) : (
              initial.items.map((item) => (
                <tr key={item.id} className="bg-white dark:bg-slate-900">
                  <td className="px-4 py-3 align-top">
                    <code className="text-xs text-slate-500 dark:text-slate-400">{item.code}</code>
                    <p className="font-medium text-slate-900 dark:text-slate-100">{item.title}</p>
                    <p className="mt-1 line-clamp-2 max-w-md text-xs text-slate-500 dark:text-slate-400">
                      {item.body}
                    </p>
                  </td>
                  <td className="px-4 py-3 align-top text-xs text-slate-700 dark:text-slate-200">
                    {item.locale}
                  </td>
                  <td className="px-4 py-3 align-top text-xs text-slate-700 dark:text-slate-200">
                    {item.category ?? "—"}
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
                        onClick={() => setDraft(draftFromTemplate(item))}
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
