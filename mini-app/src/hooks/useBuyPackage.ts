import { useMutation, useQueryClient, type UseMutationResult } from "@tanstack/react-query";

import { billingKeys } from "@/hooks/queryKeys";
import { createInvoice, fetchPaymentStatus } from "@/services/api/billing";
import { WebApp } from "@/services/telegram";
import type { InvoiceCreation, PaymentStatus, PaymentStatusValue } from "@/types/billing";

const POLL_INTERVAL_MS = 1500;
const POLL_TIMEOUT_MS = 90_000;

type OpenInvoiceStatus = "paid" | "cancelled" | "failed" | "pending" | string;

/**
 * Open a Telegram Stars invoice and resolve with the final status that
 * Telegram reports to the WebApp.  The function falls back to "pending"
 * when running outside Telegram so the polling loop still has a chance
 * to confirm the payment via the backend webhook.
 */
function openInvoice(link: string): Promise<OpenInvoiceStatus> {
  return new Promise((resolve) => {
    try {
      WebApp.openInvoice(link, (status) => {
        resolve(status as OpenInvoiceStatus);
      });
    } catch {
      resolve("pending");
    }
  });
}

const TERMINAL_STATUSES: ReadonlySet<PaymentStatusValue> = new Set([
  "completed",
  "failed",
  "cancelled",
]);

async function pollUntilTerminal(invoiceId: string): Promise<PaymentStatus> {
  const started = Date.now();
  // eslint-disable-next-line no-constant-condition
  while (true) {
    const snapshot = await fetchPaymentStatus(invoiceId);
    if (TERMINAL_STATUSES.has(snapshot.status)) {
      return snapshot;
    }
    if (Date.now() - started > POLL_TIMEOUT_MS) {
      return snapshot;
    }
    await new Promise((r) => setTimeout(r, POLL_INTERVAL_MS));
  }
}

export interface BuyPackageResult {
  invoice: InvoiceCreation;
  /** Status reported by Telegram's `openInvoice` callback. */
  telegramStatus: OpenInvoiceStatus;
  /** Final status from the backend after polling. */
  payment: PaymentStatus;
}

/**
 * Mutation that drives the full purchase flow:
 *   1. POST `/payment/create-invoice` to obtain a Stars invoice link.
 *   2. Open the link with `Telegram.WebApp.openInvoice` and wait for the
 *      user-side callback.
 *   3. Poll `/payment/status/{invoice_id}` until the backend confirms the
 *      ``successful_payment`` webhook has run (or until a timeout).
 *   4. Invalidate balance + transactions caches so the UI refreshes.
 */
export function useBuyPackage(): UseMutationResult<BuyPackageResult, Error, string> {
  const queryClient = useQueryClient();

  return useMutation<BuyPackageResult, Error, string>({
    mutationFn: async (packageCode) => {
      const invoice = await createInvoice(packageCode);
      const telegramStatus = await openInvoice(invoice.telegram_invoice_link);
      const payment = await pollUntilTerminal(invoice.invoice_id);
      return { invoice, telegramStatus, payment };
    },
    onSettled: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: billingKeys.balance() }),
        queryClient.invalidateQueries({ queryKey: billingKeys.all }),
      ]);
    },
  });
}
