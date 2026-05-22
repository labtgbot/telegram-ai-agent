import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useBuyPackage } from "@/hooks/useBuyPackage";

const fetchPaymentStatus = vi.hoisted(() => vi.fn());
const createInvoice = vi.hoisted(() => vi.fn());
const openInvoice = vi.hoisted(() => vi.fn());

vi.mock("@/services/api/billing", () => ({
  createInvoice,
  fetchPaymentStatus,
}));

vi.mock("@/services/telegram", () => ({
  WebApp: {
    openInvoice: (url: string, cb: (status: string) => void) => openInvoice(url, cb),
  },
}));

function wrapper(client: QueryClient) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  };
}

const INVOICE = {
  invoice_id: "inv_1",
  stars_amount: 250,
  tokens_amount: 500,
  telegram_invoice_link: "https://t.me/inv/abc",
  transaction_id: 42,
  is_subscription: false,
};

describe("useBuyPackage", () => {
  beforeEach(() => {
    fetchPaymentStatus.mockReset();
    createInvoice.mockReset();
    openInvoice.mockReset();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("creates an invoice, opens it, polls until completed, and invalidates billing queries", async () => {
    createInvoice.mockResolvedValue(INVOICE);
    openInvoice.mockImplementation((_url, cb) => cb("paid"));
    fetchPaymentStatus.mockResolvedValue({
      invoice_id: "inv_1",
      status: "completed",
      package: "starter",
      tokens_credited: 500,
      stars_amount: 250,
      transaction_id: 42,
      created_at: "2026-05-22T00:00:00Z",
      completed_at: "2026-05-22T00:00:30Z",
      telegram_payment_charge_id: "ch_1",
    });

    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const invalidateSpy = vi.spyOn(client, "invalidateQueries");

    const { result } = renderHook(() => useBuyPackage(), { wrapper: wrapper(client) });

    act(() => {
      result.current.mutate("starter");
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(createInvoice).toHaveBeenCalledWith("starter");
    expect(openInvoice).toHaveBeenCalledWith(INVOICE.telegram_invoice_link, expect.any(Function));
    expect(fetchPaymentStatus).toHaveBeenCalled();
    expect(result.current.data?.payment.status).toBe("completed");
    expect(invalidateSpy).toHaveBeenCalled();
  });

  it("surfaces an error when createInvoice fails", async () => {
    createInvoice.mockRejectedValue(new Error("nope"));

    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const { result } = renderHook(() => useBuyPackage(), { wrapper: wrapper(client) });

    act(() => {
      result.current.mutate("starter");
    });
    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error?.message).toBe("nope");
  });
});
