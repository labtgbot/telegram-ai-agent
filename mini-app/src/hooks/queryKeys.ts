/**
 * Centralised React Query keys for the billing flow.  Keeping the keys in
 * one module makes invalidation explicit and prevents typos like
 * `["balance"]` vs `["balances"]`.
 */
export const billingKeys = {
  all: ["billing"] as const,
  balance: () => [...billingKeys.all, "balance"] as const,
  packages: () => [...billingKeys.all, "packages"] as const,
  referral: () => [...billingKeys.all, "referral"] as const,
  transactions: (page: number, limit: number, type: string | null) =>
    [...billingKeys.all, "transactions", { page, limit, type }] as const,
  paymentStatus: (invoiceId: string) =>
    [...billingKeys.all, "payment-status", invoiceId] as const,
} as const;
