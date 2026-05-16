"use client";

import { apiClient } from "@/lib/api/browser";
import type {
  PricingConfig,
  PricingHistoryResponse,
  PricingUpdatePayload,
  PricingUpdateResponse,
} from "@/lib/admin-pricing/types";

export function getPricingConfig(): Promise<PricingConfig> {
  return apiClient().get<PricingConfig>("/admin/pricing");
}

export function getPricingHistory(page = 1, limit = 25): Promise<PricingHistoryResponse> {
  return apiClient().get<PricingHistoryResponse>("/admin/pricing/history", {
    query: { page, limit },
  });
}

export function postPricingUpdate(payload: PricingUpdatePayload): Promise<PricingUpdateResponse> {
  return apiClient().post<PricingUpdateResponse>("/admin/pricing/update", payload);
}
