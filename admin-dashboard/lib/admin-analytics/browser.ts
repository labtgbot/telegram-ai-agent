"use client";

import { apiClient } from "@/lib/api/browser";
import type {
  LtvQuery,
  LtvResponse,
  RevenueQuery,
  RevenueResponse,
  TokenUsageResponse,
  UserBehaviorQuery,
  UserBehaviorResponse,
} from "@/lib/admin-analytics/types";

function toQuery(input?: object): Record<string, string | number> {
  if (!input) return {};
  const out: Record<string, string | number> = {};
  for (const [key, value] of Object.entries(input)) {
    if (value === undefined || value === null || value === "") continue;
    out[key] = typeof value === "number" ? value : String(value);
  }
  return out;
}

export function getRevenueSummary(query?: RevenueQuery): Promise<RevenueResponse> {
  return apiClient().get<RevenueResponse>("/admin/analytics/revenue", { query: toQuery(query) });
}

export function getUserBehavior(query?: UserBehaviorQuery): Promise<UserBehaviorResponse> {
  return apiClient().get<UserBehaviorResponse>("/admin/analytics/user-behavior", {
    query: toQuery(query),
  });
}

export function getLtvSummary(query?: LtvQuery): Promise<LtvResponse> {
  return apiClient().get<LtvResponse>("/admin/analytics/ltv", { query: toQuery(query) });
}

export function getTokenUsage(query?: {
  start_date?: string;
  end_date?: string;
}): Promise<TokenUsageResponse> {
  return apiClient().get<TokenUsageResponse>("/admin/analytics/tokens", { query: toQuery(query) });
}

export function buildExportCsvUrl(query?: RevenueQuery): string {
  const params = new URLSearchParams();
  if (query?.start_date) params.set("start_date", query.start_date);
  if (query?.end_date) params.set("end_date", query.end_date);
  if (query?.group_by) params.set("group_by", query.group_by);
  const qs = params.toString();
  return qs ? `/api/admin/analytics/export.csv?${qs}` : "/api/admin/analytics/export.csv";
}
