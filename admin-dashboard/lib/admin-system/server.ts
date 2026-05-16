import "server-only";

import { createServerApiClient } from "@/lib/api/server";
import type {
  AdminUserListFilters,
  AdminUserListResponse,
  ComposioState,
  MaintenanceState,
  RateLimitsResponse,
} from "@/lib/admin-system/types";

export async function fetchMaintenanceState(): Promise<MaintenanceState> {
  const api = createServerApiClient();
  return api.get<MaintenanceState>("/admin/system/maintenance");
}

export async function fetchRateLimits(): Promise<RateLimitsResponse> {
  const api = createServerApiClient();
  return api.get<RateLimitsResponse>("/admin/system/rate-limits");
}

export async function fetchComposioState(): Promise<ComposioState> {
  const api = createServerApiClient();
  return api.get<ComposioState>("/admin/system/composio");
}

export async function fetchAdminUsers(
  filters: AdminUserListFilters = {},
): Promise<AdminUserListResponse> {
  const api = createServerApiClient();
  const query: Record<string, string | number | boolean> = {
    page: filters.page ?? 1,
    limit: filters.limit ?? 25,
  };
  if (filters.role) query.role = filters.role;
  return api.get<AdminUserListResponse>("/admin/system/admins", { query });
}
