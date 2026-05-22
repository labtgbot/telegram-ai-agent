/**
 * Type contracts for the admin Users section (issue #25).
 *
 * Mirrors the FastAPI response models in
 * `backend/app/api/v1/admin_users.py` so the server fetcher and UI share
 * a single source of truth.  Keep field names and casing in sync with
 * the backend (snake_case) — we don't translate at the boundary.
 */

export const SORT_FIELDS = [
  "created_at",
  "last_active_at",
  "token_balance",
  "total_tokens_spent",
  "total_requests",
  "telegram_id",
] as const;

export type SortField = (typeof SORT_FIELDS)[number];

export const SORT_DIRECTIONS = ["asc", "desc"] as const;
export type SortDirection = (typeof SORT_DIRECTIONS)[number];

export interface AdminUserSummary {
  id: number;
  telegram_id: number;
  username: string | null;
  first_name: string | null;
  last_name: string | null;
  language_code: string | null;
  role: string;
  is_premium: boolean;
  is_banned: boolean;
  ban_reason: string | null;
  banned_until: string | null;
  token_balance: number;
  total_tokens_purchased: number;
  total_tokens_spent: number;
  total_requests: number;
  referral_code: string;
  referred_by: number | null;
  created_at: string | null;
  last_active_at: string | null;
  last_login_at: string | null;
}

export interface UserListResponse {
  items: AdminUserSummary[];
  total: number;
  page: number;
  limit: number;
  has_more: boolean;
}

export interface TransactionRow {
  id: number;
  transaction_type: string;
  tokens_amount: number;
  stars_amount: number | null;
  package_name: string | null;
  payment_status: string | null;
  created_at: string;
  completed_at: string | null;
}

export interface ServiceUsageItem {
  service_type: string;
  requests: number;
  tokens_spent: number;
}

export interface ReferralItem {
  user_id: number;
  telegram_id: number;
  username: string | null;
  first_name: string | null;
  is_premium: boolean;
  created_at: string;
}

export interface UserStatsResponse {
  user: AdminUserSummary;
  transactions_total: number;
  recent_transactions: TransactionRow[];
  services_usage: ServiceUsageItem[];
  referrals_count: number;
  recent_referrals: ReferralItem[];
}

export interface UserListQuery {
  search?: string;
  is_premium?: boolean;
  is_banned?: boolean;
  role?: string;
  sort?: SortField;
  direction?: SortDirection;
  page?: number;
  limit?: number;
}

export interface AddTokensRequest {
  amount: number;
  reason: string;
}

export interface AddTokensResponse {
  user_id: number;
  amount: number;
  new_balance: number;
  transaction_id: number;
}

export interface BanRequest {
  reason?: string | null;
  banned_until?: string | null;
}

export interface SendMessageRequest {
  text: string;
  parse_mode?: string | null;
  disable_web_page_preview?: boolean;
}

export interface SendMessageResponse {
  delivered: boolean;
  message_id: number | null;
}

export interface AuditLogItem {
  id: number;
  admin_id: number;
  target_user_id: number | null;
  action: string;
  payload: Record<string, unknown> | null;
  ip_address: string | null;
  user_agent: string | null;
  created_at: string;
}

export interface AuditLogResponse {
  items: AuditLogItem[];
  total: number;
  page: number;
  limit: number;
  has_more: boolean;
}

export function isSortField(value: unknown): value is SortField {
  return typeof value === "string" && (SORT_FIELDS as readonly string[]).includes(value);
}

export function isSortDirection(value: unknown): value is SortDirection {
  return typeof value === "string" && (SORT_DIRECTIONS as readonly string[]).includes(value);
}
