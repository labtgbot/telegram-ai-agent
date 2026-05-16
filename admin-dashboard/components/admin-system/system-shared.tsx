"use client";

import * as React from "react";

import { cn } from "@/lib/utils";
import { isApiError } from "@/lib/api/errors";

export const textareaClass = cn(
  "w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900 shadow-sm",
  "placeholder:text-slate-400 focus-visible:outline focus-visible:outline-2 focus-visible:outline-brand-500",
  "disabled:cursor-not-allowed disabled:opacity-60 font-mono",
  "dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100 dark:placeholder:text-slate-500",
);

export const selectClass = cn(
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

export function Field({ label, hint, children }: FieldProps) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-xs font-medium text-slate-600 dark:text-slate-300">{label}</span>
      {children}
      {hint && <span className="text-[11px] text-slate-500 dark:text-slate-400">{hint}</span>}
    </label>
  );
}

export function ErrorBanner({ children }: { children: React.ReactNode }) {
  if (!children) return null;
  return (
    <p
      role="alert"
      className="rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700 dark:border-rose-700/40 dark:bg-rose-900/30 dark:text-rose-200"
    >
      {children}
    </p>
  );
}

export function SuccessBanner({ children }: { children: React.ReactNode }) {
  if (!children) return null;
  return (
    <p
      role="status"
      className="rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-700 dark:border-emerald-700/40 dark:bg-emerald-900/30 dark:text-emerald-200"
    >
      {children}
    </p>
  );
}

export function humanSystemError(err: unknown, fallback = "Request failed."): string {
  if (isApiError(err)) {
    if (err.status === 403) return "You don't have permission to perform this action.";
    if (err.status === 401) return "Your session expired — please log in again.";
    if (err.status === 404) {
      const payload = err.payload as { detail?: unknown } | undefined;
      if (typeof payload?.detail === "string") return payload.detail;
      return "Not found.";
    }
    if (err.status === 409) {
      const payload = err.payload as { detail?: unknown } | undefined;
      if (typeof payload?.detail === "string") return payload.detail;
      return "Conflict — refresh and retry.";
    }
    if (err.status === 400) {
      const payload = err.payload as { detail?: unknown } | undefined;
      if (typeof payload?.detail === "string") return payload.detail;
      return err.message || "Invalid payload.";
    }
    return err.message || `Request failed (${err.status}).`;
  }
  if (err instanceof Error) return err.message;
  return fallback;
}
