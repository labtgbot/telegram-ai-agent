/**
 * Dashboard contract returned by `GET /api/v1/admin/dashboard?period=…`.
 *
 * The shape mirrors the planned backend payload so the UI can move to the
 * upstream endpoint without changes once the analytics service ships.
 */

export const PERIODS = ["1d", "7d", "30d", "90d"] as const;
export type PeriodKey = (typeof PERIODS)[number];

export function isPeriodKey(value: unknown): value is PeriodKey {
  return typeof value === "string" && (PERIODS as readonly string[]).includes(value);
}

export interface KpiTotal {
  value: number;
  /** Percentage change vs the previous comparable window. */
  delta_pct: number;
  /** Optional absolute previous value, for tooltips. */
  previous?: number;
}

export interface UsersKpi {
  total: KpiTotal;
  new: KpiTotal;
  active: KpiTotal;
}

export interface RevenueKpi {
  /** Recurring monthly revenue in USD. */
  mrr_usd: KpiTotal;
  /** Total revenue for the selected period in USD. */
  period_usd: KpiTotal;
  /** Telegram Stars collected during the period. */
  stars: KpiTotal;
}

export interface TokensKpi {
  /** Tokens sold during the selected period. */
  sold: KpiTotal;
  /** Conversion rate (purchasers / active users) — already in percent. */
  conversion_pct: KpiTotal;
}

export interface DashboardKpis {
  users: UsersKpi;
  revenue: RevenueKpi;
  tokens: TokensKpi;
}

export interface RevenuePoint {
  /** ISO-8601 date (YYYY-MM-DD). */
  date: string;
  usd: number;
}

export interface ActivityPoint {
  date: string;
  active_users: number;
  new_users: number;
}

export type ServiceKey = "image" | "video" | "text";

export interface ServiceUsageSlice {
  service: ServiceKey;
  tokens: number;
  requests: number;
}

export interface DashboardCharts {
  revenue_30d: RevenuePoint[];
  activity_7d: ActivityPoint[];
  usage_by_service: ServiceUsageSlice[];
}

export type TransactionType = "purchase" | "refund" | "manual_bonus" | "bonus";

export interface TransactionRow {
  id: number;
  user_id: number;
  username: string | null;
  transaction_type: TransactionType;
  tokens_amount: number;
  stars_amount: number | null;
  usd_amount: number | null;
  created_at: string;
  payment_status: "pending" | "completed" | "failed" | "refunded";
}

export interface NewUserRow {
  id: number;
  telegram_id: number;
  username: string | null;
  first_name: string | null;
  language_code: string | null;
  created_at: string;
  is_premium: boolean;
}

export interface DashboardSnapshot {
  period: PeriodKey;
  generated_at: string;
  kpis: DashboardKpis;
  charts: DashboardCharts;
  latest_transactions: TransactionRow[];
  new_users: NewUserRow[];
}
