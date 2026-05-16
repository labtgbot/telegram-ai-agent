import "server-only";

import { createServerApiClient } from "@/lib/api/server";
import type {
  PricingConfig,
  PricingHistoryResponse,
  PricingUpdatePayload,
  PricingUpdateResponse,
} from "@/lib/admin-pricing/types";

export async function fetchPricingConfig(): Promise<PricingConfig> {
  const api = createServerApiClient();
  return api.get<PricingConfig>("/admin/pricing");
}

export async function fetchPricingHistory(page = 1, limit = 25): Promise<PricingHistoryResponse> {
  const api = createServerApiClient();
  return api.get<PricingHistoryResponse>("/admin/pricing/history", {
    query: { page, limit },
  });
}

export async function updatePricingConfig(
  payload: PricingUpdatePayload,
): Promise<PricingUpdateResponse> {
  const api = createServerApiClient();
  return api.post<PricingUpdateResponse>("/admin/pricing/update", payload);
}
