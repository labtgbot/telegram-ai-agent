export const SERVICE_TYPES = [
  "text",
  "image",
  "video",
  "voice",
  "search",
  "document",
  "other",
] as const;

export type ServiceType = (typeof SERVICE_TYPES)[number];

export interface UsageHistoryItem {
  id: number;
  service_type: string;
  tokens_consumed: number;
  response_status: string | null;
  processing_time_ms: number | null;
  request_params: Record<string, unknown> | null;
  created_at: string;
}

export interface UsageHistoryPage {
  items: UsageHistoryItem[];
  total: number;
  page: number;
  limit: number;
  has_more: boolean;
}

export interface UsageHistoryQuery {
  page?: number;
  limit?: number;
  service_type?: ServiceType;
}

export interface DataExportRequest {
  email: string;
}

export interface DataExportResponse {
  status: "queued" | "sent";
  email: string;
}

export interface DeleteAccountResponse {
  status: "queued" | "deleted";
}

export interface ReferralSummary {
  referral_code: string;
  referrals_count: number;
  bonus_tokens_earned: number;
  referral_link: string;
}

export function normalizeServiceType(value: string | null | undefined): ServiceType {
  if (!value) return "other";
  const lower = value.toLowerCase();
  return (SERVICE_TYPES as readonly string[]).includes(lower) ? (lower as ServiceType) : "other";
}
