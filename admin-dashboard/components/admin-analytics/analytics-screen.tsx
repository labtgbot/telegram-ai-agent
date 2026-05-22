"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { Card, CardSubtitle, CardTitle } from "@/components/ui/card";
import { FunnelChart } from "@/components/admin-analytics/funnel-chart";
import { LtvTable } from "@/components/admin-analytics/ltv-table";
import { RetentionMatrix } from "@/components/admin-analytics/retention-matrix";
import { RevenueTrendChart } from "@/components/admin-analytics/revenue-trend-chart";
import { TokenUsageTable } from "@/components/admin-analytics/token-usage-table";
import {
  buildExportCsvUrl,
  getLtvSummary,
  getRevenueSummary,
  getTokenUsage,
  getUserBehavior,
} from "@/lib/admin-analytics/browser";
import type {
  AnalyticsGroupBy,
  LtvResponse,
  RevenueResponse,
  TokenUsageResponse,
  UserBehaviorResponse,
} from "@/lib/admin-analytics/types";
import { isApiError } from "@/lib/api/errors";
import { formatInteger, formatStars, formatUsd } from "@/lib/dashboard/format";
import { cn } from "@/lib/utils";

type TabKey = "revenue" | "users" | "tokens" | "cohorts";

const TABS: Array<{ key: TabKey; label: string }> = [
  { key: "revenue", label: "Revenue" },
  { key: "users", label: "Users" },
  { key: "tokens", label: "Tokens" },
  { key: "cohorts", label: "Cohorts" },
];

const GROUP_BY_OPTIONS: AnalyticsGroupBy[] = ["day", "week", "month"];

export interface AnalyticsScreenProps {
  initialRevenue: RevenueResponse;
  initialUserBehavior: UserBehaviorResponse;
  initialTokens: TokenUsageResponse;
  initialLtv: LtvResponse;
  /** When false, the CSV export button is hidden. */
  canExport: boolean;
}

interface DateRangeState {
  start_date: string;
  end_date: string;
}

function todayIso(): string {
  return new Date().toISOString().slice(0, 10);
}

function isoNDaysAgo(days: number): string {
  const d = new Date();
  d.setUTCDate(d.getUTCDate() - days);
  return d.toISOString().slice(0, 10);
}

function humanError(err: unknown): string {
  if (isApiError(err)) {
    if (err.status === 403) return "You don't have permission to view analytics.";
    if (err.status === 401) return "Your session expired — please log in again.";
    if (err.status === 400) {
      const payload = err.payload as { detail?: { message?: string } } | undefined;
      return payload?.detail?.message ?? "Invalid analytics query.";
    }
    return err.message || `Request failed (${err.status}).`;
  }
  if (err instanceof Error) return err.message;
  return "Failed to load analytics.";
}

export function AnalyticsScreen({
  initialRevenue,
  initialUserBehavior,
  initialTokens,
  initialLtv,
  canExport,
}: AnalyticsScreenProps) {
  const [tab, setTab] = useState<TabKey>("revenue");
  const [range, setRange] = useState<DateRangeState>({
    start_date: initialRevenue.start_date,
    end_date: initialRevenue.end_date,
  });
  const [groupBy, setGroupBy] = useState<AnalyticsGroupBy>(initialRevenue.group_by);
  const [retentionWeeks, setRetentionWeeks] = useState<number>(
    initialUserBehavior.retention_weeks,
  );
  const [ltvMonths, setLtvMonths] = useState<number>(initialLtv.months);

  const [revenue, setRevenue] = useState<RevenueResponse>(initialRevenue);
  const [userBehavior, setUserBehavior] = useState<UserBehaviorResponse>(initialUserBehavior);
  const [tokens, setTokens] = useState<TokenUsageResponse>(initialTokens);
  const [ltv, setLtv] = useState<LtvResponse>(initialLtv);

  const [error, setError] = useState<string | undefined>();
  const [busy, setBusy] = useState(false);

  // Prevents the initial mount from re-fetching the data we already received
  // server-side.
  const skipNextFetch = useRef(true);

  const reload = useCallback(async () => {
    setBusy(true);
    setError(undefined);
    try {
      if (tab === "revenue") {
        const next = await getRevenueSummary({
          start_date: range.start_date,
          end_date: range.end_date,
          group_by: groupBy,
        });
        setRevenue(next);
      } else if (tab === "users") {
        const next = await getUserBehavior({
          start_date: range.start_date,
          end_date: range.end_date,
          retention_weeks: retentionWeeks,
        });
        setUserBehavior(next);
      } else if (tab === "tokens") {
        const next = await getTokenUsage({
          start_date: range.start_date,
          end_date: range.end_date,
        });
        setTokens(next);
      } else {
        const next = await getLtvSummary({ months: ltvMonths });
        setLtv(next);
      }
    } catch (err) {
      setError(humanError(err));
    } finally {
      setBusy(false);
    }
  }, [tab, range.start_date, range.end_date, groupBy, retentionWeeks, ltvMonths]);

  useEffect(() => {
    if (skipNextFetch.current) {
      skipNextFetch.current = false;
      return;
    }
    void reload();
  }, [reload]);

  const csvHref = useMemo(
    () =>
      buildExportCsvUrl({
        start_date: range.start_date,
        end_date: range.end_date,
        group_by: groupBy,
      }),
    [range.start_date, range.end_date, groupBy],
  );

  function applyPreset(days: number) {
    setRange({ start_date: isoNDaysAgo(days), end_date: todayIso() });
  }

  return (
    <div className="space-y-6">
      <nav aria-label="Analytics sections" className="flex flex-wrap gap-2 border-b border-slate-200 dark:border-slate-800">
        {TABS.map((t) => (
          <button
            key={t.key}
            type="button"
            onClick={() => setTab(t.key)}
            aria-current={tab === t.key ? "page" : undefined}
            className={cn(
              "rounded-t-md px-3 py-2 text-sm font-medium transition-colors",
              tab === t.key
                ? "border-b-2 border-brand-600 text-brand-700 dark:text-brand-300"
                : "text-slate-500 hover:text-slate-700 dark:text-slate-400 dark:hover:text-slate-200",
            )}
          >
            {t.label}
          </button>
        ))}
      </nav>

      {tab !== "cohorts" && (
        <RangeControls
          range={range}
          onChangeRange={setRange}
          onPreset={applyPreset}
          busy={busy}
          groupBy={tab === "revenue" ? groupBy : undefined}
          onChangeGroupBy={tab === "revenue" ? setGroupBy : undefined}
          retentionWeeks={tab === "users" ? retentionWeeks : undefined}
          onChangeRetentionWeeks={tab === "users" ? setRetentionWeeks : undefined}
          downloadHref={tab === "revenue" && canExport ? csvHref : undefined}
        />
      )}

      {tab === "cohorts" && (
        <LtvControls months={ltvMonths} onChange={setLtvMonths} busy={busy} />
      )}

      {error && (
        <p
          role="alert"
          className="rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700 dark:border-rose-700/40 dark:bg-rose-900/30 dark:text-rose-200"
        >
          {error}
        </p>
      )}

      {tab === "revenue" && <RevenueSection data={revenue} busy={busy} />}
      {tab === "users" && <UserBehaviorSection data={userBehavior} busy={busy} />}
      {tab === "tokens" && <TokensSection data={tokens} busy={busy} />}
      {tab === "cohorts" && <CohortsSection data={ltv} busy={busy} />}
    </div>
  );
}

interface RangeControlsProps {
  range: DateRangeState;
  onChangeRange: (range: DateRangeState) => void;
  onPreset: (days: number) => void;
  busy: boolean;
  groupBy?: AnalyticsGroupBy;
  onChangeGroupBy?: (value: AnalyticsGroupBy) => void;
  retentionWeeks?: number;
  onChangeRetentionWeeks?: (value: number) => void;
  downloadHref?: string;
}

function RangeControls({
  range,
  onChangeRange,
  onPreset,
  busy,
  groupBy,
  onChangeGroupBy,
  retentionWeeks,
  onChangeRetentionWeeks,
  downloadHref,
}: RangeControlsProps) {
  return (
    <div className="flex flex-wrap items-end gap-3 rounded-card border border-slate-200 bg-white p-3 shadow-sm dark:border-slate-800 dark:bg-slate-900">
      <DateField
        label="From"
        value={range.start_date}
        onChange={(v) => onChangeRange({ ...range, start_date: v })}
        disabled={busy}
      />
      <DateField
        label="To"
        value={range.end_date}
        onChange={(v) => onChangeRange({ ...range, end_date: v })}
        disabled={busy}
      />
      <div className="flex flex-wrap gap-1 text-xs">
        {[7, 30, 90].map((days) => (
          <button
            key={days}
            type="button"
            disabled={busy}
            onClick={() => onPreset(days)}
            className="rounded-md border border-slate-200 px-2 py-1 text-slate-600 hover:bg-slate-50 disabled:opacity-60 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
          >
            Last {days}d
          </button>
        ))}
      </div>
      {groupBy && onChangeGroupBy && (
        <label className="flex flex-col gap-1 text-xs">
          <span className="font-medium text-slate-600 dark:text-slate-300">Group by</span>
          <select
            aria-label="Group by"
            value={groupBy}
            disabled={busy}
            onChange={(e) => onChangeGroupBy(e.target.value as AnalyticsGroupBy)}
            className="h-9 rounded-md border border-slate-200 bg-white px-2 text-sm text-slate-800 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
          >
            {GROUP_BY_OPTIONS.map((opt) => (
              <option key={opt} value={opt}>
                {opt}
              </option>
            ))}
          </select>
        </label>
      )}
      {retentionWeeks !== undefined && onChangeRetentionWeeks && (
        <label className="flex flex-col gap-1 text-xs">
          <span className="font-medium text-slate-600 dark:text-slate-300">Retention weeks</span>
          <input
            aria-label="Retention weeks"
            type="number"
            min={1}
            max={26}
            value={retentionWeeks}
            disabled={busy}
            onChange={(e) => {
              const next = Number.parseInt(e.target.value, 10);
              if (Number.isFinite(next)) onChangeRetentionWeeks(next);
            }}
            className="h-9 w-24 rounded-md border border-slate-200 bg-white px-2 text-sm text-slate-800 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
          />
        </label>
      )}
      {downloadHref && (
        <a
          href={downloadHref}
          className="ml-auto inline-flex h-9 items-center rounded-md bg-brand-600 px-3 text-sm font-medium text-white hover:bg-brand-700"
        >
          Download CSV
        </a>
      )}
    </div>
  );
}

function LtvControls({
  months,
  onChange,
  busy,
}: {
  months: number;
  onChange: (months: number) => void;
  busy: boolean;
}) {
  return (
    <div className="flex flex-wrap items-end gap-3 rounded-card border border-slate-200 bg-white p-3 shadow-sm dark:border-slate-800 dark:bg-slate-900">
      <label className="flex flex-col gap-1 text-xs">
        <span className="font-medium text-slate-600 dark:text-slate-300">Lookback (months)</span>
        <input
          aria-label="Lookback months"
          type="number"
          min={1}
          max={24}
          value={months}
          disabled={busy}
          onChange={(e) => {
            const next = Number.parseInt(e.target.value, 10);
            if (Number.isFinite(next)) onChange(next);
          }}
          className="h-9 w-24 rounded-md border border-slate-200 bg-white px-2 text-sm text-slate-800 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
        />
      </label>
    </div>
  );
}

function DateField({
  label,
  value,
  onChange,
  disabled,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  disabled: boolean;
}) {
  return (
    <label className="flex flex-col gap-1 text-xs">
      <span className="font-medium text-slate-600 dark:text-slate-300">{label}</span>
      <input
        type="date"
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
        className="h-9 rounded-md border border-slate-200 bg-white px-2 text-sm text-slate-800 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
      />
    </label>
  );
}

function Kpi({
  label,
  value,
  hint,
}: {
  label: string;
  value: string;
  hint?: string;
}) {
  return (
    <div className="rounded-card border border-slate-200 bg-white p-4 shadow-sm dark:border-slate-800 dark:bg-slate-900">
      <p className="text-xs uppercase tracking-wide text-slate-500 dark:text-slate-400">{label}</p>
      <p className="mt-1 text-xl font-semibold text-slate-900 dark:text-slate-100">{value}</p>
      {hint && <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">{hint}</p>}
    </div>
  );
}

function RevenueSection({ data, busy }: { data: RevenueResponse; busy: boolean }) {
  const totalUsd = Number.parseFloat(data.total_usd) || 0;
  return (
    <section aria-label="Revenue" className="space-y-4" aria-busy={busy}>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Kpi label="Revenue $" value={formatUsd(totalUsd, { precise: true })} />
        <Kpi label="Revenue ⭐" value={formatStars(data.total_stars)} />
        <Kpi label="Purchases" value={formatInteger(data.total_purchases)} />
        <Kpi label="Tokens sold" value={formatInteger(data.total_tokens_sold)} />
      </div>
      <Card>
        <CardTitle>Revenue trend</CardTitle>
        <CardSubtitle>
          {data.start_date} → {data.end_date} · grouped by {data.group_by}
        </CardSubtitle>
        <div className="mt-4">
          <RevenueTrendChart points={data.points} />
        </div>
      </Card>
    </section>
  );
}

function UserBehaviorSection({
  data,
  busy,
}: {
  data: UserBehaviorResponse;
  busy: boolean;
}) {
  return (
    <section aria-label="User behavior" className="grid gap-6 lg:grid-cols-2" aria-busy={busy}>
      <Card>
        <CardTitle>Conversion funnel</CardTitle>
        <CardSubtitle>
          {data.start_date} → {data.end_date}
        </CardSubtitle>
        <div className="mt-4">
          <FunnelChart stages={data.funnel} />
        </div>
      </Card>
      <Card>
        <CardTitle>Weekly retention</CardTitle>
        <CardSubtitle>
          {data.retention_weeks} week{data.retention_weeks === 1 ? "" : "s"} per cohort
        </CardSubtitle>
        <div className="mt-4">
          <RetentionMatrix rows={data.retention} weeks={data.retention_weeks} />
        </div>
      </Card>
    </section>
  );
}

function TokensSection({ data, busy }: { data: TokenUsageResponse; busy: boolean }) {
  return (
    <section aria-label="Token spend" className="space-y-4" aria-busy={busy}>
      <div className="grid gap-3 sm:grid-cols-2">
        <Kpi label="Requests" value={formatInteger(data.total_requests)} />
        <Kpi label="Tokens spent" value={formatInteger(data.total_tokens_spent)} />
      </div>
      <Card>
        <CardTitle>Token spend by service</CardTitle>
        <CardSubtitle>
          {data.start_date} → {data.end_date}
        </CardSubtitle>
        <div className="mt-4">
          <TokenUsageTable
            services={data.services}
            totalRequests={data.total_requests}
            totalTokensSpent={data.total_tokens_spent}
          />
        </div>
      </Card>
    </section>
  );
}

function CohortsSection({ data, busy }: { data: LtvResponse; busy: boolean }) {
  return (
    <section aria-label="LTV cohorts" className="space-y-4" aria-busy={busy}>
      <div className="grid gap-3 sm:grid-cols-3">
        <Kpi
          label="ARPU $"
          value={formatUsd(data.overall_arpu_usd, { precise: true })}
          hint="Average revenue per registered user (all cohorts)."
        />
        <Kpi
          label="ARPU ⭐"
          value={formatStars(Math.round(data.overall_arpu_stars))}
          hint="Same window, in Stars."
        />
        <Kpi
          label="Paying rate"
          value={`${(data.overall_paying_rate * 100).toFixed(1)}%`}
          hint="Share of registered users who paid at least once."
        />
      </div>
      <Card>
        <CardTitle>Monthly cohorts</CardTitle>
        <CardSubtitle>
          Last {data.months} month{data.months === 1 ? "" : "s"} of registrations.
        </CardSubtitle>
        <div className="mt-4">
          <LtvTable cohorts={data.cohorts} />
        </div>
      </Card>
    </section>
  );
}

