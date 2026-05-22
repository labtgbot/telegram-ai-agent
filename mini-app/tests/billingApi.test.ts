import { describe, expect, it, vi } from "vitest";

import { ApiClient } from "@/services/apiClient";
import {
  createInvoice,
  fetchBalance,
  fetchPackages,
  fetchPaymentStatus,
  fetchReferral,
  fetchTransactions,
} from "@/services/api/billing";

function jsonResponse(body: unknown, init: ResponseInit = {}): Response {
  return new Response(JSON.stringify(body), {
    ...init,
    headers: { "content-type": "application/json", ...(init.headers ?? {}) },
  });
}

function makeClient(fetchImpl: ReturnType<typeof vi.fn>): ApiClient {
  return new ApiClient({
    baseUrl: "https://api.example.com/api/v1",
    getInitData: () => "tg",
    fetchImpl,
  });
}

describe("billing API", () => {
  it("calls GET /user/balance", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(
      jsonResponse({
        token_balance: 100,
        is_premium: false,
        premium_expires_at: null,
        daily_bonus_available: true,
      }),
    );
    const result = await fetchBalance(makeClient(fetchImpl));
    expect(fetchImpl).toHaveBeenCalledTimes(1);
    const [url, init] = fetchImpl.mock.calls[0]!;
    expect(url).toBe("https://api.example.com/api/v1/user/balance");
    expect(init!.method).toBe("GET");
    expect(result.token_balance).toBe(100);
  });

  it("calls GET /payment/packages", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse({ items: [] }));
    await fetchPackages(makeClient(fetchImpl));
    expect(fetchImpl.mock.calls[0]![0]).toBe(
      "https://api.example.com/api/v1/payment/packages",
    );
  });

  it("calls GET /user/transactions with pagination and filter", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(
      jsonResponse({ items: [], total: 0, page: 1, limit: 10, has_more: false }),
    );
    await fetchTransactions({ page: 2, limit: 5, type: "purchase" }, makeClient(fetchImpl));
    expect(fetchImpl.mock.calls[0]![0]).toBe(
      "https://api.example.com/api/v1/user/transactions?page=2&limit=5&type=purchase",
    );
  });

  it("omits the type filter when null", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(
      jsonResponse({ items: [], total: 0, page: 1, limit: 10, has_more: false }),
    );
    await fetchTransactions({ page: 1, limit: 10, type: null }, makeClient(fetchImpl));
    expect(fetchImpl.mock.calls[0]![0]).toBe(
      "https://api.example.com/api/v1/user/transactions?page=1&limit=10",
    );
  });

  it("calls GET /user/referral", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(
      jsonResponse({
        referral_code: "abc",
        referral_link: "https://t.me/bot?start=ref_abc",
        bot_username: "bot",
        start_param: "ref_abc",
      }),
    );
    const data = await fetchReferral(makeClient(fetchImpl));
    expect(fetchImpl.mock.calls[0]![0]).toBe(
      "https://api.example.com/api/v1/user/referral",
    );
    expect(data.referral_code).toBe("abc");
  });

  it("POSTs to /payment/create-invoice with the package code", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(
      jsonResponse({
        invoice_id: "x",
        stars_amount: 1,
        tokens_amount: 1,
        telegram_invoice_link: "y",
        transaction_id: 1,
        is_subscription: false,
      }),
    );
    await createInvoice("starter", makeClient(fetchImpl));
    const [url, init] = fetchImpl.mock.calls[0]!;
    expect(url).toBe("https://api.example.com/api/v1/payment/create-invoice");
    expect(init!.method).toBe("POST");
    expect(init!.body).toBe(JSON.stringify({ package: "starter" }));
  });

  it("encodes the invoice id when fetching status", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(
      jsonResponse({
        invoice_id: "weird id",
        status: "pending",
        package: null,
        tokens_credited: 0,
        stars_amount: null,
        transaction_id: 1,
        created_at: "2026-01-01T00:00:00Z",
        completed_at: null,
        telegram_payment_charge_id: null,
      }),
    );
    await fetchPaymentStatus("weird id", makeClient(fetchImpl));
    expect(fetchImpl.mock.calls[0]![0]).toBe(
      "https://api.example.com/api/v1/payment/status/weird%20id",
    );
  });
});
