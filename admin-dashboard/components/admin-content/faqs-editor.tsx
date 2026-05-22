"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { deleteFaqItem, postFaqItem, putFaqItem } from "@/lib/admin-content/browser";
import type {
  FaqItem,
  FaqItemListResponse,
  FaqItemPayload,
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

interface FaqsEditorProps {
  initial: FaqItemListResponse;
  canEdit: boolean;
}

interface Draft {
  id: number | null;
  question: string;
  answer: string;
  category: string;
  locale: string;
  sort_order: number;
  is_active: boolean;
}

function blankDraft(): Draft {
  return {
    id: null,
    question: "",
    answer: "",
    category: "",
    locale: "en",
    sort_order: 0,
    is_active: true,
  };
}

function draftFromItem(item: FaqItem): Draft {
  return {
    id: item.id,
    question: item.question,
    answer: item.answer,
    category: item.category ?? "",
    locale: item.locale,
    sort_order: item.sort_order,
    is_active: item.is_active,
  };
}

function buildPayload(draft: Draft): { payload?: FaqItemPayload; error?: string } {
  const question = draft.question.trim();
  const answer = draft.answer.trim();
  if (!question) return { error: "Question is required." };
  if (!answer) return { error: "Answer is required." };
  return {
    payload: {
      question,
      answer,
      category: draft.category.trim() || null,
      locale: draft.locale.trim() || "en",
      sort_order: Number.isFinite(draft.sort_order) ? draft.sort_order : 0,
      is_active: draft.is_active,
    },
  };
}

export function FaqsEditor({ initial, canEdit }: FaqsEditorProps) {
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
        const created = await postFaqItem(payload);
        setSuccess(`Created FAQ #${created.id}.`);
      } else {
        const updated = await putFaqItem(draft.id, payload);
        setSuccess(`Saved changes to FAQ #${updated.id}.`);
      }
      setDraft(blankDraft());
      router.refresh();
    } catch (err) {
      setError(humanContentError(err, "Failed to save FAQ."));
    } finally {
      setBusy(false);
    }
  }

  async function handleDelete(item: FaqItem) {
    if (!canEdit) return;
    if (!window.confirm(`Delete FAQ #${item.id}? This cannot be undone.`)) return;
    setBusy(true);
    setError(undefined);
    try {
      await deleteFaqItem(item.id);
      setSuccess(`Deleted FAQ #${item.id}.`);
      if (draft.id === item.id) setDraft(blankDraft());
      router.refresh();
    } catch (err) {
      setError(humanContentError(err, "Failed to delete FAQ."));
    } finally {
      setBusy(false);
    }
  }

  const disabled = !canEdit || busy;
  const isEditing = draft.id !== null;

  return (
    <section
      aria-label="FAQ items"
      className="space-y-4 rounded-card border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900"
    >
      <header className="flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-100">FAQ items</h2>
          <p className="text-sm text-slate-500 dark:text-slate-400">
            {initial.total === 0 ? "No FAQ entries yet." : `${initial.total} entries.`}
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

      <Field label="Question">
        <Input
          value={draft.question}
          onChange={(e) => patch({ question: e.target.value })}
          disabled={disabled}
          placeholder="How do I top up my balance?"
          maxLength={500}
        />
      </Field>

      <Field label="Answer">
        <textarea
          rows={5}
          value={draft.answer}
          onChange={(e) => patch({ answer: e.target.value })}
          disabled={disabled}
          className={textareaClass}
          placeholder="You can top up via Telegram Stars from /balance."
        />
      </Field>

      <div className="grid gap-3 lg:grid-cols-4">
        <Field label="Category">
          <Input
            value={draft.category}
            onChange={(e) => patch({ category: e.target.value })}
            disabled={disabled}
            placeholder="billing"
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
          {isEditing ? (busy ? "Saving…" : "Save changes") : busy ? "Creating…" : "Create FAQ"}
        </Button>
      </div>

      <div className="overflow-x-auto rounded-md border border-slate-200 dark:border-slate-800">
        <table className="min-w-full divide-y divide-slate-200 text-sm dark:divide-slate-800">
          <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500 dark:bg-slate-900/40 dark:text-slate-400">
            <tr>
              <th scope="col" className="px-4 py-3 text-left font-semibold">Question / answer</th>
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
                  No FAQ entries yet.
                </td>
              </tr>
            ) : (
              initial.items.map((item) => (
                <tr key={item.id} className="bg-white dark:bg-slate-900">
                  <td className="px-4 py-3 align-top">
                    <p className="font-medium text-slate-900 dark:text-slate-100">{item.question}</p>
                    <p className="mt-1 line-clamp-2 max-w-md text-xs text-slate-500 dark:text-slate-400">
                      {item.answer}
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
