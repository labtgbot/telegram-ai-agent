"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

interface UsersFiltersProps {
  initialSearch: string;
  initialPremium: boolean | undefined;
  initialBanned: boolean | undefined;
  csvHref: string;
}

const PREMIUM_OPTIONS = [
  { value: "", label: "Premium · any" },
  { value: "true", label: "Premium · only" },
  { value: "false", label: "Premium · excluded" },
] as const;

const BANNED_OPTIONS = [
  { value: "", label: "Banned · any" },
  { value: "true", label: "Banned · only" },
  { value: "false", label: "Banned · excluded" },
] as const;

export function UsersFilters({
  initialSearch,
  initialPremium,
  initialBanned,
  csvHref,
}: UsersFiltersProps) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [search, setSearch] = useState(initialSearch);

  const navigateWith = useCallback(
    (mutate: (params: URLSearchParams) => void) => {
      const params = new URLSearchParams(searchParams?.toString() ?? "");
      mutate(params);
      // Filter changes reset pagination.
      params.delete("page");
      const qs = params.toString();
      router.push(qs ? `/users?${qs}` : "/users");
    },
    [router, searchParams],
  );

  const submitSearch = useCallback(
    (event: React.FormEvent<HTMLFormElement>) => {
      event.preventDefault();
      navigateWith((params) => {
        if (search.trim()) params.set("search", search.trim());
        else params.delete("search");
      });
    },
    [navigateWith, search],
  );

  const setSelectFilter = useCallback(
    (key: "is_premium" | "is_banned", value: string) => {
      navigateWith((params) => {
        if (value === "") params.delete(key);
        else params.set(key, value);
      });
    },
    [navigateWith],
  );

  const clearFilters = useCallback(() => {
    setSearch("");
    router.push("/users");
  }, [router]);

  const premiumValue = useMemo(() => boolToParam(initialPremium), [initialPremium]);
  const bannedValue = useMemo(() => boolToParam(initialBanned), [initialBanned]);

  const hasFilters = Boolean(
    initialSearch || initialPremium !== undefined || initialBanned !== undefined,
  );

  return (
    <div className="flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-center">
      <form onSubmit={submitSearch} className="flex flex-1 items-center gap-2 sm:max-w-md">
        <Input
          key={initialSearch}
          name="search"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search username, @handle, or telegram id"
          aria-label="Search users"
        />
        <Button type="submit" variant="secondary" size="md">
          Search
        </Button>
      </form>
      <FilterSelect
        label="Premium filter"
        value={premiumValue}
        options={PREMIUM_OPTIONS}
        onChange={(v) => setSelectFilter("is_premium", v)}
      />
      <FilterSelect
        label="Banned filter"
        value={bannedValue}
        options={BANNED_OPTIONS}
        onChange={(v) => setSelectFilter("is_banned", v)}
      />
      {hasFilters && (
        <Button variant="ghost" size="md" onClick={clearFilters}>
          Clear filters
        </Button>
      )}
      <div className="sm:ml-auto">
        <a
          href={csvHref}
          className={cn(
            "inline-flex h-10 items-center justify-center rounded-md border border-slate-200 bg-white px-4 text-sm font-medium",
            "text-slate-700 shadow-sm hover:bg-slate-50",
            "dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100 dark:hover:bg-slate-800",
          )}
        >
          Export CSV
        </a>
      </div>
    </div>
  );
}

interface FilterSelectProps {
  label: string;
  value: string;
  options: readonly { value: string; label: string }[];
  onChange: (value: string) => void;
}

function FilterSelect({ label, value, options, onChange }: FilterSelectProps) {
  return (
    <label className="text-xs text-slate-500 dark:text-slate-400">
      <span className="sr-only">{label}</span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        aria-label={label}
        className={cn(
          "h-10 rounded-md border border-slate-200 bg-white px-3 text-sm text-slate-900 shadow-sm",
          "focus-visible:outline focus-visible:outline-2 focus-visible:outline-brand-500",
          "dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100",
        )}
      >
        {options.map((opt) => (
          <option key={opt.value} value={opt.value}>
            {opt.label}
          </option>
        ))}
      </select>
    </label>
  );
}

function boolToParam(value: boolean | undefined): string {
  if (value === true) return "true";
  if (value === false) return "false";
  return "";
}
