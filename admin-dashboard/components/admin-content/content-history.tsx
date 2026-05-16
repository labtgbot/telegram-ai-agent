"use client";

import type { AuditLogListResponse } from "@/lib/admin-content/types";
import { formatDateTime } from "@/lib/dashboard/format";

interface ContentHistoryProps {
  initial: AuditLogListResponse;
}

const ACTION_LABEL: Record<string, string> = {
  "prompt_template.created": "Prompt template created",
  "prompt_template.updated": "Prompt template updated",
  "prompt_template.deleted": "Prompt template deleted",
  "faq_item.created": "FAQ created",
  "faq_item.updated": "FAQ updated",
  "faq_item.deleted": "FAQ deleted",
  "welcome_message.created": "Welcome created",
  "welcome_message.updated": "Welcome updated",
  "welcome_message.deleted": "Welcome deleted",
};

function summarisePayload(payload: Record<string, unknown> | null): string {
  if (!payload) return "—";
  const code = typeof payload.code === "string" ? payload.code : undefined;
  const name = typeof payload.name === "string" ? payload.name : undefined;
  const question = typeof payload.question === "string" ? payload.question : undefined;
  const id = typeof payload.id === "number" ? payload.id : undefined;
  const parts: string[] = [];
  if (id !== undefined) parts.push(`#${id}`);
  if (code) parts.push(code);
  if (name) parts.push(name);
  if (question) parts.push(question.length > 80 ? `${question.slice(0, 77)}…` : question);
  return parts.join(" · ") || "—";
}

export function ContentHistory({ initial }: ContentHistoryProps) {
  return (
    <section
      aria-label="Content change history"
      className="space-y-3 rounded-card border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900"
    >
      <header>
        <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-100">Change history</h2>
        <p className="text-sm text-slate-500 dark:text-slate-400">
          {initial.total === 0
            ? "No mutations yet."
            : `Last ${initial.items.length} of ${initial.total} entries (newest first).`}
        </p>
      </header>

      {initial.items.length === 0 ? (
        <p className="rounded-md border border-dashed border-slate-200 px-4 py-8 text-center text-sm text-slate-500 dark:border-slate-700 dark:text-slate-400">
          Nothing yet — admin actions on prompt templates, FAQs, and welcomes will appear here.
        </p>
      ) : (
        <div className="overflow-x-auto rounded-md border border-slate-200 dark:border-slate-800">
          <table className="min-w-full divide-y divide-slate-200 text-sm dark:divide-slate-800">
            <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500 dark:bg-slate-900/40 dark:text-slate-400">
              <tr>
                <th scope="col" className="px-4 py-3 text-left font-semibold">When</th>
                <th scope="col" className="px-4 py-3 text-left font-semibold">Action</th>
                <th scope="col" className="px-4 py-3 text-left font-semibold">Entity</th>
                <th scope="col" className="px-4 py-3 text-left font-semibold">Admin</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
              {initial.items.map((entry) => (
                <tr key={entry.id} className="bg-white dark:bg-slate-900">
                  <td className="px-4 py-3 align-top text-xs text-slate-500 dark:text-slate-400">
                    {formatDateTime(entry.created_at)}
                  </td>
                  <td className="px-4 py-3 align-top text-sm text-slate-700 dark:text-slate-200">
                    {ACTION_LABEL[entry.action] ?? entry.action}
                  </td>
                  <td className="px-4 py-3 align-top text-xs text-slate-600 dark:text-slate-300">
                    {summarisePayload(entry.payload)}
                  </td>
                  <td className="px-4 py-3 align-top text-xs text-slate-500 dark:text-slate-400">
                    admin #{entry.admin_id}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
