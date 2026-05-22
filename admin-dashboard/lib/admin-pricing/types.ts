/**
 * Type contracts for the admin Pricing section (issue #26).
 *
 * Mirrors the FastAPI response models in
 * `backend/app/api/v1/admin_pricing.py` so the server fetcher, the
 * browser fetcher, and the editor share a single source of truth.
 * Keep field names snake_case to match the wire format.
 */

export interface PricingPackage {
  code: string;
  title: string;
  description: string;
  tokens: number;
  stars: number;
  discount: number;
  is_subscription: boolean;
}

export interface PricingLimits {
  max_discount_percent: number;
  max_tokens_per_package: number;
  max_stars_per_package: number;
  max_bonus_tokens: number;
}

export interface PricingConfig {
  packages: PricingPackage[];
  global_discount: number;
  seasonal_promo: number;
  first_purchase_bonus: number;
  referral_bonus: number;
  daily_bonus: number;
  currency_rate: number;
  limits: PricingLimits;
}

export interface PricingPackageUpdate {
  tokens?: number;
  stars?: number;
  discount?: number;
}

export interface PricingUpdatePayload {
  packages?: Record<string, PricingPackageUpdate>;
  global_discount?: number;
  seasonal_promo?: number;
  first_purchase_bonus?: number;
  referral_bonus?: number;
  daily_bonus?: number;
  currency_rate?: number;
}

export interface PricingUpdateResponse {
  config: PricingConfig;
  diff: Record<string, unknown>;
  audit_log_id: number;
}

export interface PricingHistoryItem {
  id: number;
  admin_id: number;
  diff: Record<string, unknown> | null;
  snapshot: Record<string, unknown> | null;
  ip_address: string | null;
  user_agent: string | null;
  created_at: string;
}

export interface PricingHistoryResponse {
  items: PricingHistoryItem[];
  total: number;
  page: number;
  limit: number;
  has_more: boolean;
}
