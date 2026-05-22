import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { TransactionList } from "@/components/billing/TransactionList";
import type { TransactionsResponse } from "@/types/billing";

const SAMPLE: TransactionsResponse = {
  items: [
    {
      id: 1,
      transaction_type: "purchase",
      tokens_amount: 1200,
      stars_amount: 500,
      package_name: "Basic",
      payment_status: "completed",
      payment_method: "stars",
      created_at: "2026-05-01T10:00:00Z",
      completed_at: "2026-05-01T10:00:30Z",
    },
    {
      id: 2,
      transaction_type: "spend",
      tokens_amount: 50,
      stars_amount: null,
      package_name: null,
      payment_status: null,
      payment_method: null,
      created_at: "2026-05-02T11:00:00Z",
      completed_at: null,
    },
  ],
  total: 25,
  page: 1,
  limit: 10,
  has_more: true,
};

describe("TransactionList", () => {
  it("renders each transaction with proper sign", () => {
    render(
      <TransactionList
        data={SAMPLE}
        isLoading={false}
        error={null}
        page={1}
        filter={null}
        onPageChange={() => undefined}
        onFilterChange={() => undefined}
      />,
    );
    expect(screen.getByTestId("tx-1")).toHaveTextContent("+1 200");
    expect(screen.getByTestId("tx-1")).toHaveTextContent("Basic");
    expect(screen.getByTestId("tx-2")).toHaveTextContent("-50");
  });

  it("calls onFilterChange when a filter chip is clicked", async () => {
    const onFilterChange = vi.fn();
    render(
      <TransactionList
        data={SAMPLE}
        isLoading={false}
        error={null}
        page={1}
        filter={null}
        onPageChange={() => undefined}
        onFilterChange={onFilterChange}
      />,
    );
    await userEvent.click(screen.getByTestId("tx-filter-purchase"));
    expect(onFilterChange).toHaveBeenCalledWith("purchase");
  });

  it("calls onPageChange when Next is clicked", async () => {
    const onPageChange = vi.fn();
    render(
      <TransactionList
        data={SAMPLE}
        isLoading={false}
        error={null}
        page={1}
        filter={null}
        onPageChange={onPageChange}
        onFilterChange={() => undefined}
      />,
    );
    await userEvent.click(screen.getByTestId("tx-next"));
    expect(onPageChange).toHaveBeenCalledWith(2);
  });

  it("disables Next when has_more is false", () => {
    render(
      <TransactionList
        data={{ ...SAMPLE, has_more: false }}
        isLoading={false}
        error={null}
        page={3}
        filter={null}
        onPageChange={() => undefined}
        onFilterChange={() => undefined}
      />,
    );
    expect(screen.getByTestId("tx-next")).toBeDisabled();
  });

  it("renders empty state when items is empty", () => {
    render(
      <TransactionList
        data={{ items: [], total: 0, page: 1, limit: 10, has_more: false }}
        isLoading={false}
        error={null}
        page={1}
        filter={null}
        onPageChange={() => undefined}
        onFilterChange={() => undefined}
      />,
    );
    expect(screen.getByTestId("transactions-empty")).toBeInTheDocument();
  });
});
