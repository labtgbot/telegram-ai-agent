"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { Card, CardSubtitle, CardTitle } from "@/components/ui/card";
import { ActivityChart } from "@/components/dashboard/activity-chart";
import { KpiCard } from "@/components/dashboard/kpi-card";
import { PeriodSelector } from "@/components/dashboard/period-selector";
import { RevenueChart } from "@/components/dashboard/revenue-chart";
import { TransactionsList } from "@/components/dashboard/transactions-list";
import { UsageChart } from "@/components/dashboard/usage-chart";
import { UsersList } from "@/components/dashboard/users-list";
import { cn } from "@/lib/utils";
import {
  formatDateTime,
  formatInteger,
  formatNumberCompact,
  formatPercent,
  formatRelative,
  formatStars,
  formatUsd,
} from "@/lib/dashboard/format";
import {
  PERIODS,
  type DashboardSnapshot,
  type PeriodKey,
} from "@/lib/dashboard/types";

export interface DashboardScreenProps {
  initialSnapshot: DashboardSnapshot;
  /** Polling interval in milliseconds (acceptance criterion: 30s). */
  refreshIntervalMs?: number;
}

const PERIOD_LABEL: Record<PeriodKey, string> = {
  "1d": "last 24 hours",
  "7d": "last 7 days",
  "30d": "last 30 days",
  "90d": "last 90 days",
};

interface FetchState {
  data: DashboardSnapshot;
  loading: boolean;
  error: string | undefined;
  lastUpdatedAt: string;
}

async function fetchSnapshot(period: PeriodKey, signal: AbortSignal): Promise<DashboardSnapshot> {
  const response = await fetch(`/api/admin/dashboard?period=${period}`, {
    cache: "no-store",
    signal,
    headers: { Accept: "application/json" },
  });
  if (!response.ok) {
    throw new Error(`dashboard request failed: ${response.status}`);
  }
  return (await response.json()) as DashboardSnapshot;
}

export function DashboardScreen({
  initialSnapshot,
  refreshIntervalMs = 30_000,
}: DashboardScreenProps) {
  const [period, setPeriod] = useState<PeriodKey>(initialSnapshot.period);
  const [state, setState] = useState<FetchState>(() => ({
    data: initialSnapshot,
    loading: false,
    error: undefined,
    lastUpdatedAt: initialSnapshot.generated_at,
  }));
  const inFlight = useRef<AbortController | null>(null);
  const [tick, setTick] = useState(0);

  const refresh = useCallback(
    async (next: PeriodKey, mode: "interval" | "manual" | "switch" = "manual") => {
      inFlight.current?.abort();
      const controller = new AbortController();
      inFlight.current = controller;
      setState((prev) => ({ ...prev, loading: true, error: undefined }));
      try {
        const snapshot = await fetchSnapshot(next, controller.signal);
        if (controller.signal.aborted) return;
        setState({
          data: snapshot,
          loading: false,
          error: undefined,
          lastUpdatedAt: snapshot.generated_at,
        });
      } catch (err) {
        if (controller.signal.aborted) return;
        const message = err instanceof Error ? err.message : "unknown_error";
        setState((prev) => ({ ...prev, loading: false, error: message }));
        if (mode === "manual") {
          // Surface manual failures; interval failures are silent (will retry).
          console.error("dashboard refresh failed", err);
        }
      }
    },
    [],
  );

  // Drive a tick every minute so "Updated 2m ago" stays fresh without
  // re-fetching.
  useEffect(() => {
    const id = window.setInterval(() => setTick((n) => n + 1), 60_000);
    return () => window.clearInterval(id);
  }, []);

  // Auto-refresh polling.
  useEffect(() => {
    const id = window.setInterval(() => {
      void refresh(period, "interval");
    }, refreshIntervalMs);
    return () => window.clearInterval(id);
  }, [period, refresh, refreshIntervalMs]);

  // Cleanup pending request on unmount.
  useEffect(() => {
    return () => {
      inFlight.current?.abort();
    };
  }, []);

  const handlePeriodChange = useCallback(
    (next: PeriodKey) => {
      if (next === period) return;
      setPeriod(next);
      void refresh(next, "switch");
    },
    [period, refresh],
  );

  const data = state.data;
  const kpis = data.kpis;
  // `tick` participates in the dep array on purpose: it advances every minute
  // and forces the relative label to recompute even when `lastUpdatedAt`
  // hasn't changed.
  const updatedLabel = useMemo(
    () => formatRelative(state.lastUpdatedAt),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [state.lastUpdatedAt, tick],
  );

  return (
    <div className="space-y-6">
      <header className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900 dark:text-slate-100">Dashboard</h1>
          <p className="text-sm text-slate-500 dark:text-slate-400">
            KPIs, charts and live activity for the {PERIOD_LABEL[period]}.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <PeriodSelector value={period} onChange={handlePeriodChange} disabled={state.loading} />
          <RefreshIndicator
            updatedLabel={updatedLabel}
            updatedIso={state.lastUpdatedAt}
            loading={state.loading}
            error={state.error}
            onRefresh={() => void refresh(period, "manual")}
          />
        </div>
      </header>

      <section
        aria-label="Key performance indicators"
        className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4"
      >
        <KpiCard
          label="Users total"
          value={formatNumberCompact(kpis.users.total.value)}
          hint={`+${formatInteger(kpis.users.new.value)} new in ${period}`}
          delta_pct={kpis.users.total.delta_pct}
        />
        <KpiCard
          label="Active users"
          value={formatNumberCompact(kpis.users.active.value)}
          hint="Touched the bot recently"
          delta_pct={kpis.users.active.delta_pct}
        />
        <KpiCard
          label="MRR"
          value={formatUsd(kpis.revenue.mrr_usd.value)}
          hint={`Period revenue ${formatUsd(kpis.revenue.period_usd.value)}`}
          delta_pct={kpis.revenue.mrr_usd.delta_pct}
        />
        <KpiCard
          label="Tokens sold"
          value={formatNumberCompact(kpis.tokens.sold.value)}
          hint={`${formatStars(kpis.revenue.stars.value)} collected`}
          delta_pct={kpis.tokens.sold.delta_pct}
        />
        <KpiCard
          label="Revenue (period)"
          value={formatUsd(kpis.revenue.period_usd.value)}
          hint={`vs ${formatUsd(kpis.revenue.period_usd.previous ?? 0)} previous`}
          delta_pct={kpis.revenue.period_usd.delta_pct}
        />
        <KpiCard
          label="New users"
          value={formatInteger(kpis.users.new.value)}
          hint={`Conversion ${formatPercent(kpis.tokens.conversion_pct.value)}`}
          delta_pct={kpis.users.new.delta_pct}
        />
        <KpiCard
          label="Conversion"
          value={formatPercent(kpis.tokens.conversion_pct.value)}
          hint="Purchasers / active"
          delta_pct={kpis.tokens.conversion_pct.delta_pct}
        />
        <KpiCard
          label="Stars (period)"
          value={formatStars(kpis.revenue.stars.value)}
          hint={`${formatUsd(kpis.revenue.period_usd.value)} ≈ ${formatNumberCompact(kpis.revenue.stars.value)} ⭐`}
          delta_pct={kpis.revenue.stars.delta_pct}
        />
      </section>

      <section className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2" aria-label="Revenue chart">
          <CardTitle>Revenue · last 30 days</CardTitle>
          <CardSubtitle>Daily Stars-to-USD revenue, dotted lines mark quartile bands.</CardSubtitle>
          <div className="mt-4">
            <RevenueChart data={data.charts.revenue_30d} />
          </div>
        </Card>
        <Card aria-label="Service usage chart">
          <CardTitle>Usage by service</CardTitle>
          <CardSubtitle>Tokens consumed per service in the selected period.</CardSubtitle>
          <div className="mt-4">
            <UsageChart data={data.charts.usage_by_service} />
          </div>
        </Card>
      </section>

      <section className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card aria-label="Activity chart">
          <CardTitle>Activity · last 7 days</CardTitle>
          <CardSubtitle>Active vs. new users, stacked per day.</CardSubtitle>
          <div className="mt-4">
            <ActivityChart data={data.charts.activity_7d} />
          </div>
        </Card>
        <Card aria-label="Latest transactions">
          <CardTitle>Latest transactions</CardTitle>
          <CardSubtitle>
            Live feed — refreshes every {Math.round(refreshIntervalMs / 1000)}s alongside the rest of the page.
          </CardSubtitle>
          <div className="mt-4">
            <TransactionsList rows={data.latest_transactions} />
          </div>
        </Card>
      </section>

      <section className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card aria-label="New users">
          <CardTitle>New users</CardTitle>
          <CardSubtitle>Recent registrations, newest first.</CardSubtitle>
          <div className="mt-4">
            <UsersList rows={data.new_users} />
          </div>
        </Card>
        <Card aria-label="Period summary">
          <CardTitle>Period at a glance</CardTitle>
          <CardSubtitle>Quick sanity-check numbers for the {PERIOD_LABEL[period]}.</CardSubtitle>
          <dl className="mt-4 grid grid-cols-2 gap-4 text-sm">
            <Pair label="Total users" value={formatInteger(kpis.users.total.value)} />
            <Pair label="Active users" value={formatInteger(kpis.users.active.value)} />
            <Pair label="New users" value={formatInteger(kpis.users.new.value)} />
            <Pair label="Tokens sold" value={formatInteger(kpis.tokens.sold.value)} />
            <Pair label="Period revenue" value={formatUsd(kpis.revenue.period_usd.value)} />
            <Pair label="Stars collected" value={formatStars(kpis.revenue.stars.value)} />
            <Pair label="MRR" value={formatUsd(kpis.revenue.mrr_usd.value)} />
            <Pair label="Conversion" value={formatPercent(kpis.tokens.conversion_pct.value)} />
          </dl>
        </Card>
      </section>
    </div>
  );
}

function Pair({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col gap-0.5">
      <dt className="text-xs uppercase tracking-wide text-slate-500 dark:text-slate-400">{label}</dt>
      <dd className="text-base font-semibold tabular-nums text-slate-900 dark:text-slate-100">{value}</dd>
    </div>
  );
}

interface RefreshIndicatorProps {
  updatedLabel: string;
  updatedIso: string;
  loading: boolean;
  error: string | undefined;
  onRefresh: () => void;
}

function RefreshIndicator({ updatedLabel, updatedIso, loading, error, onRefresh }: RefreshIndicatorProps) {
  const stateLabel = error ? `Refresh failed (${error})` : loading ? "Refreshing…" : `Updated ${updatedLabel}`;
  return (
    <div
      className={cn(
        "flex items-center gap-2 rounded-md border border-slate-200 bg-white px-3 py-1.5 text-xs shadow-sm",
        "dark:border-slate-700 dark:bg-slate-900",
        error && "border-rose-300 text-rose-700 dark:border-rose-700/60 dark:text-rose-200",
      )}
      title={`Last sync: ${formatDateTime(updatedIso)}`}
    >
      <span
        aria-hidden
        className={cn(
          "h-2 w-2 rounded-full",
          loading ? "animate-pulse bg-amber-500" : error ? "bg-rose-500" : "bg-emerald-500",
        )}
      />
      <span data-testid="refresh-state" className="text-slate-600 dark:text-slate-300">
        {stateLabel}
      </span>
      <button
        type="button"
        onClick={onRefresh}
        disabled={loading}
        className="text-brand-600 hover:underline disabled:cursor-not-allowed disabled:opacity-50 dark:text-brand-300"
      >
        Refresh
      </button>
    </div>
  );
}

export const DASHBOARD_SUPPORTED_PERIODS = PERIODS;
