"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { cn } from "@/lib/utils";

const NAV: Array<{ href: string; label: string }> = [
  { href: "/dashboard", label: "Dashboard" },
  { href: "/users", label: "Users" },
  { href: "/transactions", label: "Transactions" },
  { href: "/pricing", label: "Pricing" },
  { href: "/analytics", label: "Analytics" },
  { href: "/broadcast", label: "Broadcast" },
  { href: "/content", label: "Content" },
  { href: "/system", label: "System" },
  { href: "/settings", label: "Settings" },
];

export function Sidebar() {
  const pathname = usePathname();

  return (
    <nav
      aria-label="Primary"
      className="flex h-full w-60 shrink-0 flex-col gap-1 border-r border-slate-200 bg-white px-3 py-6 dark:border-slate-800 dark:bg-slate-950"
    >
      <div className="px-3 pb-4">
        <p className="text-sm font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">
          Admin CRM
        </p>
        <p className="text-xs text-slate-400">Telegram AI Agent</p>
      </div>
      <ul className="flex flex-col gap-1">
        {NAV.map((item) => {
          const active = pathname === item.href || pathname.startsWith(`${item.href}/`);
          return (
            <li key={item.href}>
              <Link
                href={item.href}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "block rounded-md px-3 py-2 text-sm font-medium transition-colors",
                  active
                    ? "bg-brand-100 text-brand-900 dark:bg-brand-900/40 dark:text-brand-100"
                    : "text-slate-700 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-900",
                )}
              >
                {item.label}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
