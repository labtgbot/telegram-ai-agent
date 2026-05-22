import { apiClient, type ApiClient } from "@/services/apiClient";
import type {
  Balance,
  InvoiceCreation,
  PackagesResponse,
  PaymentStatus,
  ReferralInfo,
  TransactionType,
  TransactionsResponse,
} from "@/types/billing";

/**
 * Thin functional wrapper around `ApiClient` for the billing / balance
 * endpoints.  Each function maps 1:1 onto a backend route declared in
 * `backend/app/api/v1/user.py` or `backend/app/api/v1/payment.py`.
 *
 * The default `client` argument is the shared `apiClient` singleton; tests
 * can inject a stub.  All functions return the parsed JSON body and throw
 * `ApiError` on non-2xx.
 */

export interface FetchTransactionsArgs {
  page?: number;
  limit?: number;
  type?: TransactionType | null;
}

export function fetchBalance(client: ApiClient = apiClient): Promise<Balance> {
  return client.get<Balance>("/user/balance");
}

export function fetchPackages(client: ApiClient = apiClient): Promise<PackagesResponse> {
  return client.get<PackagesResponse>("/payment/packages");
}

export function fetchTransactions(
  { page = 1, limit = 20, type = null }: FetchTransactionsArgs = {},
  client: ApiClient = apiClient,
): Promise<TransactionsResponse> {
  return client.get<TransactionsResponse>("/user/transactions", {
    query: { page, limit, type: type ?? undefined },
  });
}

export function fetchReferral(client: ApiClient = apiClient): Promise<ReferralInfo> {
  return client.get<ReferralInfo>("/user/referral");
}

export function createInvoice(
  packageCode: string,
  client: ApiClient = apiClient,
): Promise<InvoiceCreation> {
  return client.post<InvoiceCreation>("/payment/create-invoice", { package: packageCode });
}

export function fetchPaymentStatus(
  invoiceId: string,
  client: ApiClient = apiClient,
): Promise<PaymentStatus> {
  return client.get<PaymentStatus>(`/payment/status/${encodeURIComponent(invoiceId)}`);
}
