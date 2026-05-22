/**
 * Domain types for the balance + purchase flow.
 *
 * Mirrors the Pydantic responses in
 *   - `backend/app/api/v1/user.py` (BalanceResponse, TransactionsResponse, ReferralResponse)
 *   - `backend/app/api/v1/payment.py` (PackagesResponse, CreateInvoiceResponse, PaymentStatusResponse)
 */

export interface Balance {
  token_balance: number;
  is_premium: boolean;
  premium_expires_at: string | null;
  daily_bonus_available: boolean;
}

export interface PackageItem {
  code: string;
  title: string;
  description: string;
  tokens: number;
  stars: number;
  is_subscription: boolean;
  subscription_days: number;
}

export interface PackagesResponse {
  items: PackageItem[];
}

export type TransactionType = "purchase" | "spend" | "bonus" | "refund" | "manual_bonus";

export interface TransactionItem {
  id: number;
  transaction_type: TransactionType;
  tokens_amount: number;
  stars_amount: number | null;
  package_name: string | null;
  payment_status: string | null;
  payment_method: string | null;
  created_at: string;
  completed_at: string | null;
}

export interface TransactionsResponse {
  items: TransactionItem[];
  total: number;
  page: number;
  limit: number;
  has_more: boolean;
}

export interface ReferralInfo {
  referral_code: string;
  referrals_count: number;
  bonus_tokens_earned: number;
  referral_link: string;
}

export interface InvoiceCreation {
  invoice_id: string;
  stars_amount: number;
  tokens_amount: number;
  telegram_invoice_link: string;
  transaction_id: number;
  is_subscription: boolean;
}

export type PaymentStatusValue =
  | "pending"
  | "completed"
  | "failed"
  | "cancelled"
  | string;

export interface PaymentStatus {
  invoice_id: string;
  status: PaymentStatusValue;
  package: string | null;
  tokens_credited: number;
  stars_amount: number | null;
  transaction_id: number;
  created_at: string;
  completed_at: string | null;
  telegram_payment_charge_id: string | null;
}
