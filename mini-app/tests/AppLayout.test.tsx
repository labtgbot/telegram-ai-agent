import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/services/userApi", () => ({
  userApi: {
    getDailyBonusStatus: vi.fn().mockResolvedValue({
      available: false,
      enabled: true,
      streak_day: 0,
      next_amount: 10,
      last_claim_date: null,
      next_available_at: "2026-05-17T00:00:00+00:00",
      amounts: [10, 12, 15, 20],
    }),
    claimDailyBonus: vi.fn(),
  },
  ApiError: class ApiError extends Error {
    status: number;
    body: unknown;
    constructor(message: string, status: number, body: unknown) {
      super(message);
      this.status = status;
      this.body = body;
    }
  },
}));

import { AppLayout } from "@/layouts/AppLayout";
import { BalancePage } from "@/pages/BalancePage";
import { HomePage } from "@/pages/HomePage";

function renderAt(path: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const router = createMemoryRouter(
    [
      {
        path: "/",
        element: <AppLayout />,
        children: [
          { index: true, element: <HomePage /> },
          { path: "balance", element: <BalancePage /> },
        ],
      },
    ],
    { initialEntries: [path] },
  );
  return render(
    <QueryClientProvider client={client}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
}

describe("AppLayout", () => {
  const originalFetch = globalThis.fetch;
  beforeEach(() => {
    globalThis.fetch = vi.fn(
      () =>
        new Promise(() => {
          /* never resolves — queries stay in loading state */
        }),
    ) as typeof fetch;
  });
  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  it("renders home content at /", () => {
    renderAt("/");
    expect(screen.getByText("Welcome")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Telegram AI Agent" })).toBeInTheDocument();
  });

  it("renders the balance page heading at /balance", () => {
    renderAt("/balance");
    expect(screen.getByTestId("balance-card")).toBeInTheDocument();
    expect(screen.getByTestId("balance")).toBeInTheDocument();
  });

  it("exposes the active colour scheme", () => {
    renderAt("/");
    expect(screen.getByTestId("active-scheme")).toBeInTheDocument();
  });
});
