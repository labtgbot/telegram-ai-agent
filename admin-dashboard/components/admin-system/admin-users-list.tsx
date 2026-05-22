"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

import { Button } from "@/components/ui/button";
import { putAdminRole } from "@/lib/admin-system/browser";
import type { AdminUser, AdminUserListResponse } from "@/lib/admin-system/types";
import { formatDateTime, formatRelative } from "@/lib/dashboard/format";

import {
  ErrorBanner,
  SuccessBanner,
  humanSystemError,
  selectClass,
} from "./system-shared";

interface AdminUsersListProps {
  initial: AdminUserListResponse;
  canEdit: boolean;
  currentUserId?: number;
}

const ROLE_LABEL: Record<string, string> = {
  super_admin: "Super admin",
  support_admin: "Support admin",
  analyst: "Analyst",
  user: "User (demote)",
  banned: "Banned",
};

const ROLE_CLASS: Record<string, string> = {
  super_admin: "bg-violet-100 text-violet-800 dark:bg-violet-500/20 dark:text-violet-200",
  support_admin: "bg-sky-100 text-sky-800 dark:bg-sky-500/20 dark:text-sky-200",
  analyst: "bg-emerald-100 text-emerald-800 dark:bg-emerald-500/20 dark:text-emerald-200",
  user: "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300",
  banned: "bg-rose-100 text-rose-800 dark:bg-rose-500/20 dark:text-rose-200",
};

export function AdminUsersList({ initial, canEdit, currentUserId }: AdminUsersListProps) {
  const router = useRouter();
  const [draftRole, setDraftRole] = useState<Record<number, string>>({});
  const [busyId, setBusyId] = useState<number | null>(null);
  const [error, setError] = useState<string | undefined>();
  const [success, setSuccess] = useState<string | undefined>();

  const assignableRoles = initial.assignable_roles.length > 0
    ? initial.assignable_roles
    : ["analyst", "support_admin", "super_admin", "user"];

  async function changeRole(user: AdminUser) {
    if (!canEdit) return;
    const nextRole = draftRole[user.id];
    if (!nextRole || nextRole === user.role) {
      setError("Pick a different role first.");
      return;
    }
    if (
      !window.confirm(
        `Change role of admin #${user.id} (@${user.username ?? user.first_name ?? user.telegram_id}) ` +
          `from ${user.role} to ${nextRole}?`,
      )
    ) {
      return;
    }
    setBusyId(user.id);
    setError(undefined);
    setSuccess(undefined);
    try {
      const updated = await putAdminRole(user.id, { role: nextRole });
      setSuccess(`Updated admin #${updated.id} to ${updated.role}.`);
      setDraftRole((prev) => {
        const next = { ...prev };
        delete next[user.id];
        return next;
      });
      router.refresh();
    } catch (err) {
      setError(humanSystemError(err, "Failed to change role."));
    } finally {
      setBusyId(null);
    }
  }

  return (
    <section
      aria-label="Admin users"
      className="space-y-3 rounded-card border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900"
    >
      <header>
        <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-100">Admin users</h2>
        <p className="text-sm text-slate-500 dark:text-slate-400">
          {initial.total} admin{initial.total === 1 ? "" : "s"}.{" "}
          {canEdit
            ? "Promotion / demotion is logged. You can&apos;t demote the last super admin."
            : "Read-only — super-admin role required to change roles."}
        </p>
      </header>

      <ErrorBanner>{error}</ErrorBanner>
      <SuccessBanner>{success}</SuccessBanner>

      {initial.items.length === 0 ? (
        <p className="rounded-md border border-dashed border-slate-200 px-4 py-8 text-center text-sm text-slate-500 dark:border-slate-700 dark:text-slate-400">
          No admins yet.
        </p>
      ) : (
        <div className="overflow-x-auto rounded-md border border-slate-200 dark:border-slate-800">
          <table className="min-w-full divide-y divide-slate-200 text-sm dark:divide-slate-800">
            <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500 dark:bg-slate-900/40 dark:text-slate-400">
              <tr>
                <th scope="col" className="px-4 py-3 text-left font-semibold">Admin</th>
                <th scope="col" className="px-4 py-3 text-left font-semibold">Role</th>
                <th scope="col" className="px-4 py-3 text-left font-semibold">Last login</th>
                <th scope="col" className="px-4 py-3 text-left font-semibold">Last active</th>
                <th scope="col" className="px-4 py-3 text-right font-semibold">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
              {initial.items.map((user) => {
                const isSelf = currentUserId !== undefined && currentUserId === user.id;
                const isBusy = busyId === user.id;
                const draft = draftRole[user.id] ?? user.role;
                return (
                  <tr key={user.id} className="bg-white dark:bg-slate-900">
                    <td className="px-4 py-3 align-top">
                      <p className="font-medium text-slate-900 dark:text-slate-100">
                        {[user.first_name, user.last_name].filter(Boolean).join(" ") ||
                          user.username ||
                          `Admin #${user.id}`}
                        {isSelf && (
                          <span className="ml-2 text-[11px] uppercase tracking-wider text-brand-600 dark:text-brand-300">
                            you
                          </span>
                        )}
                      </p>
                      <p className="text-xs text-slate-500 dark:text-slate-400">
                        @{user.username ?? "—"} · TG #{user.telegram_id}
                      </p>
                      <p className="mt-1 text-[11px] text-slate-400">
                        joined {formatDateTime(user.created_at)}
                      </p>
                    </td>
                    <td className="px-4 py-3 align-top">
                      <span
                        className={
                          "inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium " +
                          (ROLE_CLASS[user.role] ?? ROLE_CLASS.user)
                        }
                      >
                        {ROLE_LABEL[user.role] ?? user.role}
                      </span>
                      {user.is_banned && (
                        <p className="mt-1 text-[11px] text-rose-600 dark:text-rose-300">Banned</p>
                      )}
                    </td>
                    <td className="px-4 py-3 align-top text-xs text-slate-600 dark:text-slate-300">
                      {user.last_login_at ? formatRelative(user.last_login_at) : "—"}
                    </td>
                    <td className="px-4 py-3 align-top text-xs text-slate-600 dark:text-slate-300">
                      {user.last_active_at ? formatRelative(user.last_active_at) : "—"}
                    </td>
                    <td className="px-4 py-3 align-top text-right">
                      <div className="flex items-center justify-end gap-2">
                        <select
                          className={selectClass + " w-44"}
                          value={draft}
                          onChange={(e) =>
                            setDraftRole((prev) => ({ ...prev, [user.id]: e.target.value }))
                          }
                          disabled={!canEdit || isBusy}
                          aria-label={`Role for admin #${user.id}`}
                        >
                          {assignableRoles.map((role) => (
                            <option key={role} value={role}>
                              {ROLE_LABEL[role] ?? role}
                            </option>
                          ))}
                          {!assignableRoles.includes(user.role) && (
                            <option value={user.role}>{ROLE_LABEL[user.role] ?? user.role}</option>
                          )}
                        </select>
                        <Button
                          variant="primary"
                          size="sm"
                          onClick={() => changeRole(user)}
                          disabled={!canEdit || isBusy || draft === user.role}
                        >
                          {isBusy ? "Saving…" : "Apply"}
                        </Button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
