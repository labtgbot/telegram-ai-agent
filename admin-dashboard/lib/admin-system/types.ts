/**
 * Type contracts for the admin System Settings section (issue #29).
 *
 * Mirrors the FastAPI response models in
 * `backend/app/api/v1/admin_system.py`. Wire format stays snake_case.
 */

export interface MaintenanceState {
  enabled: boolean;
  message: string | null;
  updated_at: string | null;
  updated_by: number | null;
}

export interface MaintenanceUpdatePayload {
  enabled: boolean;
  message?: string | null;
}

// ------------------------------------------------------------------- rate limits

export interface RateLimitRule {
  limit: number;
  window_seconds: number;
}

export type RateLimitPlanMap = Record<string, Record<string, RateLimitRule>>;

export interface RateLimitsResponse {
  plans: RateLimitPlanMap;
  overrides: Record<string, Record<string, RateLimitRule>>;
  defaults: RateLimitPlanMap;
  updated_at: string | null;
  updated_by: number | null;
}

export interface RateLimitsUpdatePayload {
  overrides: Record<string, Record<string, RateLimitRule>> | null;
}

// -------------------------------------------------------------------- composio

export interface ComposioState {
  enabled_tools: string[];
  config: Record<string, unknown>;
  updated_at: string | null;
  updated_by: number | null;
}

export interface ComposioUpdatePayload {
  enabled_tools: string[];
  config?: Record<string, unknown> | null;
}

// ----------------------------------------------------------------- admin users

export interface AdminUser {
  id: number;
  telegram_id: number;
  username: string | null;
  first_name: string | null;
  last_name: string | null;
  role: string;
  is_banned: boolean;
  last_login_at: string | null;
  last_active_at: string | null;
  created_at: string;
}

export interface AdminUserListResponse {
  items: AdminUser[];
  total: number;
  page: number;
  limit: number;
  has_more: boolean;
  assignable_roles: string[];
}

export interface AdminUserListFilters {
  role?: string;
  page?: number;
  limit?: number;
}

export interface AdminRoleUpdatePayload {
  role: string;
}
