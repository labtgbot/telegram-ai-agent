"use client";

import { apiClient } from "@/lib/api/browser";
import type {
  BroadcastCreateRequest,
  BroadcastListResponse,
  BroadcastResponse,
  BroadcastStatsResponse,
  BroadcastStatus,
  PreviewAudienceRequest,
  PreviewAudienceResponse,
} from "@/lib/admin-broadcasts/types";

export interface BroadcastListFilters {
  status?: BroadcastStatus;
  page?: number;
  limit?: number;
}

export function getBroadcasts(filters: BroadcastListFilters = {}): Promise<BroadcastListResponse> {
  const query: Record<string, string | number> = {};
  if (filters.status) query.status = filters.status;
  query.page = filters.page ?? 1;
  query.limit = filters.limit ?? 25;
  return apiClient().get<BroadcastListResponse>("/admin/broadcasts", { query });
}

export function getBroadcast(id: number): Promise<BroadcastResponse> {
  return apiClient().get<BroadcastResponse>(`/admin/broadcasts/${id}`);
}

export function getBroadcastStats(id: number): Promise<BroadcastStatsResponse> {
  return apiClient().get<BroadcastStatsResponse>(`/admin/broadcasts/${id}/stats`);
}

export function postBroadcast(payload: BroadcastCreateRequest): Promise<BroadcastResponse> {
  return apiClient().post<BroadcastResponse>("/admin/broadcasts", payload);
}

export function postPreviewAudience(
  payload: PreviewAudienceRequest,
): Promise<PreviewAudienceResponse> {
  return apiClient().post<PreviewAudienceResponse>("/admin/broadcasts/preview-audience", payload);
}

export function postCancelBroadcast(id: number): Promise<BroadcastResponse> {
  return apiClient().post<BroadcastResponse>(`/admin/broadcasts/${id}/cancel`, {});
}
