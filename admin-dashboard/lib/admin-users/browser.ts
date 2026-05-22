"use client";

import { apiClient } from "@/lib/api/browser";
import type {
  AddTokensRequest,
  AddTokensResponse,
  AdminUserSummary,
  BanRequest,
  SendMessageRequest,
  SendMessageResponse,
  UserListQuery,
  UserListResponse,
  UserStatsResponse,
} from "@/lib/admin-users/types";

function toQuery(filters: UserListQuery) {
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

export function listUsers(filters: UserListQuery = {}): Promise<UserListResponse> {
  return apiClient().get<UserListResponse>("/admin/users", { query: toQuery(filters) });
}

export function getUserStats(userId: number): Promise<UserStatsResponse> {
  return apiClient().get<UserStatsResponse>(`/admin/users/${userId}/stats`);
}

export function addTokens(
  userId: number,
  payload: AddTokensRequest,
): Promise<AddTokensResponse> {
  return apiClient().post<AddTokensResponse>(`/admin/users/${userId}/add-tokens`, payload);
}

export function banUser(userId: number, payload: BanRequest): Promise<AdminUserSummary> {
  return apiClient().post<AdminUserSummary>(`/admin/users/${userId}/ban`, payload);
}

export function unbanUser(userId: number): Promise<AdminUserSummary> {
  return apiClient().post<AdminUserSummary>(`/admin/users/${userId}/unban`);
}

export function sendUserMessage(
  userId: number,
  payload: SendMessageRequest,
): Promise<SendMessageResponse> {
  return apiClient().post<SendMessageResponse>(`/admin/users/${userId}/message`, payload);
}
