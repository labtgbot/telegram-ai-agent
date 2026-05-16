import "server-only";

import { createServerApiClient } from "@/lib/api/server";
import type {
  AddTokensRequest,
  AddTokensResponse,
  AdminUserSummary,
  AuditLogResponse,
  BanRequest,
  SendMessageRequest,
  SendMessageResponse,
  UserListQuery,
  UserListResponse,
  UserStatsResponse,
} from "@/lib/admin-users/types";

function listQuery(filters: UserListQuery): Record<string, string | number | boolean | undefined> {
  return {
    search: filters.search?.trim() || undefined,
    is_premium: filters.is_premium,
    is_banned: filters.is_banned,
    role: filters.role,
    sort: filters.sort,
    direction: filters.direction,
    page: filters.page,
    limit: filters.limit,
  };
}

export async function fetchUsers(filters: UserListQuery = {}): Promise<UserListResponse> {
  const api = createServerApiClient();
  return api.get<UserListResponse>("/admin/users", { query: listQuery(filters) });
}

export async function fetchUserStats(userId: number): Promise<UserStatsResponse> {
  const api = createServerApiClient();
  return api.get<UserStatsResponse>(`/admin/users/${userId}/stats`);
}

export async function fetchUser(userId: number): Promise<AdminUserSummary> {
  const api = createServerApiClient();
  return api.get<AdminUserSummary>(`/admin/users/${userId}`);
}

export async function addUserTokens(
  userId: number,
  payload: AddTokensRequest,
): Promise<AddTokensResponse> {
  const api = createServerApiClient();
  return api.post<AddTokensResponse>(`/admin/users/${userId}/add-tokens`, payload);
}

export async function banUser(userId: number, payload: BanRequest): Promise<AdminUserSummary> {
  const api = createServerApiClient();
  return api.post<AdminUserSummary>(`/admin/users/${userId}/ban`, payload);
}

export async function unbanUser(userId: number): Promise<AdminUserSummary> {
  const api = createServerApiClient();
  return api.post<AdminUserSummary>(`/admin/users/${userId}/unban`);
}

export async function sendUserMessage(
  userId: number,
  payload: SendMessageRequest,
): Promise<SendMessageResponse> {
  const api = createServerApiClient();
  return api.post<SendMessageResponse>(`/admin/users/${userId}/message`, payload);
}

export async function fetchAuditLog(opts: {
  adminId?: number;
  targetUserId?: number;
  action?: string;
  page?: number;
  limit?: number;
} = {}): Promise<AuditLogResponse> {
  const api = createServerApiClient();
  return api.get<AuditLogResponse>("/admin/audit-log", {
    query: {
      admin_id: opts.adminId,
      target_user_id: opts.targetUserId,
      action: opts.action,
      page: opts.page,
      limit: opts.limit,
    },
  });
}

export function exportUsersCsvUrl(filters: UserListQuery = {}): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(listQuery(filters))) {
    if (value === undefined) continue;
    params.set(key, String(value));
  }
  const qs = params.toString();
  return qs ? `/api/admin/users/export.csv?${qs}` : "/api/admin/users/export.csv";
}
