import "server-only";

import { createServerApiClient } from "@/lib/api/server";
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

export async function fetchRevenueSummary(query?: RevenueQuery): Promise<RevenueResponse> {
  const api = createServerApiClient();
  return api.get<RevenueResponse>("/admin/analytics/revenue", { query: toQuery(query) });
}

export async function fetchUserBehavior(
  query?: UserBehaviorQuery,
): Promise<UserBehaviorResponse> {
  const api = createServerApiClient();
  return api.get<UserBehaviorResponse>("/admin/analytics/user-behavior", {
    query: toQuery(query),
  });
}

export async function fetchLtvSummary(query?: LtvQuery): Promise<LtvResponse> {
  const api = createServerApiClient();
  return api.get<LtvResponse>("/admin/analytics/ltv", { query: toQuery(query) });
}

export async function fetchTokenUsage(query?: {
  start_date?: string;
  end_date?: string;
}): Promise<TokenUsageResponse> {
  const api = createServerApiClient();
  return api.get<TokenUsageResponse>("/admin/analytics/tokens", { query: toQuery(query) });
}
