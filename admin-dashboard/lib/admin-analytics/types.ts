/**
 * Type contracts for the admin Analytics section (issue #27).
 *
 * Mirrors the FastAPI response models in
 * `backend/app/api/v1/admin_analytics.py` — keep field names snake_case
 * to match the wire format.
 *
 * Decimal-valued fields (`usd`, `revenue_usd`, etc.) arrive as strings
 * because they originate from `Numeric` columns; `parseFloat` them when
 * a chart needs to plot them.
 */

export type AnalyticsGroupBy = "day" | "week" | "month";

export interface AnalyticsApiErrorDetail {
  code: "invalid_range" | "invalid_group_by";
  message: string;
}

export interface RevenuePoint {
  bucket: string; // ISO date (YYYY-MM-DD)
  purchases: number;
  stars: number;
  usd: string; // Decimal serialised as string
  tokens_sold: number;
}

export interface RevenueResponse {
  start_date: string;
  end_date: string;
  group_by: AnalyticsGroupBy;
  total_stars: number;
  total_usd: string;
  total_tokens_sold: number;
  total_purchases: number;
  points: RevenuePoint[];
}

export interface FunnelStage {
  key: "registered" | "activated" | "paid" | "repeat" | "premium" | string;
  label: string;
  users: number;
  conversion_from_previous: number;
  conversion_from_top: number;
}

export interface RetentionRow {
  cohort: string;
  cohort_size: number;
  retained: number[];
  rates: number[];
}

export interface UserBehaviorResponse {
  start_date: string;
  end_date: string;
  retention_weeks: number;
  funnel: FunnelStage[];
  retention: RetentionRow[];
}

export interface LtvCohort {
  cohort: string;
  cohort_size: number;
  paying_users: number;
  revenue_stars: number;
  revenue_usd: string;
  ltv_stars: number;
  ltv_usd: number;
  avg_revenue_per_paying: number;
}

export interface LtvResponse {
  months: number;
  overall_arpu_stars: number;
  overall_arpu_usd: number;
  overall_paying_rate: number;
  cohorts: LtvCohort[];
}

export interface TokenUsagePoint {
  service_type: string;
  requests: number;
  tokens_spent: number;
  share: number;
}

export interface TokenUsageResponse {
  start_date: string;
  end_date: string;
  total_requests: number;
  total_tokens_spent: number;
  services: TokenUsagePoint[];
}

export interface AnalyticsRangeQuery {
  start_date?: string;
  end_date?: string;
}

export interface RevenueQuery extends AnalyticsRangeQuery {
  group_by?: AnalyticsGroupBy;
}

export interface UserBehaviorQuery extends AnalyticsRangeQuery {
  retention_weeks?: number;
}

export interface LtvQuery {
  months?: number;
}
