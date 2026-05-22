"use client";

import { apiClient } from "@/lib/api/browser";
import type {
  AdminRoleUpdatePayload,
  AdminUser,
  AdminUserListFilters,
  AdminUserListResponse,
  ComposioState,
  ComposioUpdatePayload,
  MaintenanceState,
  MaintenanceUpdatePayload,
  RateLimitsResponse,
  RateLimitsUpdatePayload,
} from "@/lib/admin-system/types";

// ----------------------------------------------------------------- maintenance

export function getMaintenanceState(): Promise<MaintenanceState> {
  return apiClient().get<MaintenanceState>("/admin/system/maintenance");
}

export function putMaintenanceState(
  payload: MaintenanceUpdatePayload,
): Promise<MaintenanceState> {
  return apiClient().request<MaintenanceState>("/admin/system/maintenance", {
    method: "PUT",
    body: payload,
  });
}

// ----------------------------------------------------------------- rate limits

export function getRateLimits(): Promise<RateLimitsResponse> {
  return apiClient().get<RateLimitsResponse>("/admin/system/rate-limits");
}

export function putRateLimits(payload: RateLimitsUpdatePayload): Promise<RateLimitsResponse> {
  return apiClient().request<RateLimitsResponse>("/admin/system/rate-limits", {
    method: "PUT",
    body: payload,
  });
}

// ------------------------------------------------------------------- composio

export function getComposioState(): Promise<ComposioState> {
  return apiClient().get<ComposioState>("/admin/system/composio");
}

export function putComposioState(payload: ComposioUpdatePayload): Promise<ComposioState> {
  return apiClient().request<ComposioState>("/admin/system/composio", {
    method: "PUT",
    body: payload,
  });
}

// ----------------------------------------------------------------- admin users

export function getAdminUsers(
  filters: AdminUserListFilters = {},
): Promise<AdminUserListResponse> {
  const query: Record<string, string | number | boolean> = {
    page: filters.page ?? 1,
    limit: filters.limit ?? 25,
  };
  if (filters.role) query.role = filters.role;
  return apiClient().get<AdminUserListResponse>("/admin/system/admins", { query });
}

export function putAdminRole(
  userId: number,
  payload: AdminRoleUpdatePayload,
): Promise<AdminUser> {
  return apiClient().request<AdminUser>(`/admin/system/admins/${userId}/role`, {
    method: "PUT",
    body: payload,
  });
}
