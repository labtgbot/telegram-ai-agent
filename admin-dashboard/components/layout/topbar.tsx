"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { csrfHeaders } from "@/lib/auth/csrf";

export interface TopbarProps {
  role: string;
  sub: string;
}

export function Topbar({ role, sub }: TopbarProps) {
  const router = useRouter();
  const [pending, setPending] = useState(false);

  async function logout() {
    setPending(true);
    try {
      await fetch("/api/auth/logout", {
        method: "POST",
        headers: csrfHeaders(),
        credentials: "include",
      });
    } finally {
      setPending(false);
      router.replace("/login");
      router.refresh();
    }
  }

  return (
    <header className="flex h-14 items-center justify-between border-b border-slate-200 bg-white px-6 dark:border-slate-800 dark:bg-slate-950">
      <div className="text-sm text-slate-500 dark:text-slate-400">
        Signed in as <span className="font-medium text-slate-700 dark:text-slate-200">#{sub}</span>{" "}
        <span className="ml-1 rounded-full bg-brand-100 px-2 py-0.5 text-xs font-medium text-brand-700 dark:bg-brand-900/40 dark:text-brand-200">
          {role}
        </span>
      </div>
      <Button variant="secondary" size="sm" onClick={logout} disabled={pending}>
        {pending ? "Signing out..." : "Sign out"}
      </Button>
    </header>
  );
}
