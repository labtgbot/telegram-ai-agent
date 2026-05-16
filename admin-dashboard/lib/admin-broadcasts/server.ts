import "server-only";

import { createServerApiClient } from "@/lib/api/server";
import type {
  BroadcastListResponse,
  BroadcastResponse,
  BroadcastStatsResponse,
  BroadcastStatus,
} from "@/lib/admin-broadcasts/types";

export interface BroadcastListFilters {
  status?: BroadcastStatus;
  page?: number;
  limit?: number;
}

export async function fetchBroadcasts(
  filters: BroadcastListFilters = {},
): Promise<BroadcastListResponse> {
  const api = createServerApiClient();
  const query: Record<string, string | number> = {};
  if (filters.status) query.status = filters.status;
  query.page = filters.page ?? 1;
  query.limit = filters.limit ?? 25;
  return api.get<BroadcastListResponse>("/admin/broadcasts", { query });
}

export async function fetchBroadcast(id: number): Promise<BroadcastResponse> {
  const api = createServerApiClient();
  return api.get<BroadcastResponse>(`/admin/broadcasts/${id}`);
}

export async function fetchBroadcastStats(id: number): Promise<BroadcastStatsResponse> {
  const api = createServerApiClient();
  return api.get<BroadcastStatsResponse>(`/admin/broadcasts/${id}/stats`);
}

export async function fetchAudiences(): Promise<string[]> {
  const api = createServerApiClient();
  const payload = await api.get<{ audiences: string[] }>("/admin/broadcasts/audiences");
  return payload.audiences;
}
