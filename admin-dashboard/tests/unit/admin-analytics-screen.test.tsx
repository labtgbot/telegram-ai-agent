import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { AnalyticsScreen } from "@/components/admin-analytics/analytics-screen";
import type {
  LtvResponse,
  RevenueResponse,
  TokenUsageResponse,
  UserBehaviorResponse,
} from "@/lib/admin-analytics/types";

const getRevenueSummary = vi.fn();
const getUserBehavior = vi.fn();
const getTokenUsage = vi.fn();
const getLtvSummary = vi.fn();
const buildExportCsvUrl = vi.fn();

vi.mock("@/lib/admin-analytics/browser", () => ({
  getRevenueSummary: (...args: unknown[]) => getRevenueSummary(...args),
  getUserBehavior: (...args: unknown[]) => getUserBehavior(...args),
  getTokenUsage: (...args: unknown[]) => getTokenUsage(...args),
  getLtvSummary: (...args: unknown[]) => getLtvSummary(...args),
  buildExportCsvUrl: (...args: unknown[]) => buildExportCsvUrl(...args),
}));

function makeRevenue(overrides: Partial<RevenueResponse> = {}): RevenueResponse {
  return {
    start_date: "2026-05-01",
    end_date: "2026-05-15",
    group_by: "day",
    total_stars: 1_200,
    total_usd: "15.60",
    total_tokens_sold: 60_000,
    total_purchases: 12,
    points: [
      { bucket: "2026-05-01", purchases: 5, stars: 500, usd: "6.50", tokens_sold: 25_000 },
      { bucket: "2026-05-02", purchases: 7, stars: 700, usd: "9.10", tokens_sold: 35_000 },
    ],
    ...overrides,
  };
}

function makeUserBehavior(
  overrides: Partial<UserBehaviorResponse> = {},
): UserBehaviorResponse {
  return {
    start_date: "2026-05-01",
    end_date: "2026-05-15",
    retention_weeks: 4,
    funnel: [
      { key: "registered", label: "Registered", users: 100, conversion_from_previous: 1, conversion_from_top: 1 },
      { key: "activated", label: "Activated", users: 80, conversion_from_previous: 0.8, conversion_from_top: 0.8 },
      { key: "paid", label: "Paid", users: 30, conversion_from_previous: 0.375, conversion_from_top: 0.3 },
      { key: "repeat", label: "Repeat buyer", users: 12, conversion_from_previous: 0.4, conversion_from_top: 0.12 },
      { key: "premium", label: "Premium", users: 5, conversion_from_previous: 0.417, conversion_from_top: 0.05 },
    ],
    retention: [
      {
        cohort: "2026-05-04",
        cohort_size: 40,
        retained: [40, 18, 12, 7],
        rates: [1, 0.45, 0.3, 0.175],
      },
    ],
    ...overrides,
  };
}

function makeTokens(overrides: Partial<TokenUsageResponse> = {}): TokenUsageResponse {
  return {
    start_date: "2026-05-01",
    end_date: "2026-05-15",
    total_requests: 1_500,
    total_tokens_spent: 250_000,
    services: [
      { service_type: "text_generation", requests: 1_200, tokens_spent: 200_000, share: 0.8 },
      { service_type: "image_generation", requests: 300, tokens_spent: 50_000, share: 0.2 },
    ],
    ...overrides,
  };
}

function makeLtv(overrides: Partial<LtvResponse> = {}): LtvResponse {
  return {
    months: 6,
    overall_arpu_stars: 12,
    overall_arpu_usd: 0.16,
    overall_paying_rate: 0.18,
    cohorts: [
      {
        cohort: "2026-04-01",
        cohort_size: 100,
        paying_users: 25,
        revenue_stars: 5_000,
        revenue_usd: "65.00",
        ltv_stars: 50,
        ltv_usd: 0.65,
        avg_revenue_per_paying: 2.6,
      },
    ],
    ...overrides,
  };
}

function renderScreen(canExport = true) {
  return render(
    <AnalyticsScreen
      initialRevenue={makeRevenue()}
      initialUserBehavior={makeUserBehavior()}
      initialTokens={makeTokens()}
      initialLtv={makeLtv()}
      canExport={canExport}
    />,
  );
}

describe("<AnalyticsScreen />", () => {
  beforeEach(() => {
    getRevenueSummary.mockReset();
    getUserBehavior.mockReset();
    getTokenUsage.mockReset();
    getLtvSummary.mockReset();
    buildExportCsvUrl.mockReset();
    buildExportCsvUrl.mockReturnValue("/api/admin/analytics/export.csv?group_by=day");
  });
  afterEach(() => cleanup());

  it("renders the four tab buttons and Revenue KPIs by default", () => {
    renderScreen();
    expect(screen.getByRole("button", { name: "Revenue" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Users" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Tokens" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Cohorts" })).toBeInTheDocument();
    expect(screen.getByText("Revenue $")).toBeInTheDocument();
    expect(screen.getByText("$15.60")).toBeInTheDocument();
    expect(screen.getByText("1,200 ⭐")).toBeInTheDocument();
  });

  it("shows the CSV download link when canExport is true on the Revenue tab", () => {
    renderScreen(true);
    const link = screen.getByRole("link", { name: /Download CSV/i });
    expect(link).toHaveAttribute("href", "/api/admin/analytics/export.csv?group_by=day");
  });

  it("hides the CSV download link when canExport is false", () => {
    renderScreen(false);
    expect(screen.queryByRole("link", { name: /Download CSV/i })).toBeNull();
  });

  it("does not refetch on initial mount (server-provided data)", async () => {
    renderScreen();
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(getRevenueSummary).not.toHaveBeenCalled();
    expect(getUserBehavior).not.toHaveBeenCalled();
    expect(getTokenUsage).not.toHaveBeenCalled();
    expect(getLtvSummary).not.toHaveBeenCalled();
  });

  it("switches to Users tab and fetches user behavior data", async () => {
    const user = userEvent.setup();
    getUserBehavior.mockResolvedValue(makeUserBehavior());
    renderScreen();

    await user.click(screen.getByRole("button", { name: "Users" }));

    await waitFor(() => {
      expect(getUserBehavior).toHaveBeenCalledTimes(1);
    });
    expect(getUserBehavior).toHaveBeenCalledWith({
      start_date: "2026-05-01",
      end_date: "2026-05-15",
      retention_weeks: 4,
    });
    expect(screen.getByText("Conversion funnel")).toBeInTheDocument();
    expect(screen.getByText("Weekly retention")).toBeInTheDocument();
  });

  it("switches to Tokens tab, renders the table and refetches", async () => {
    const user = userEvent.setup();
    getTokenUsage.mockResolvedValue(makeTokens());
    renderScreen();

    await user.click(screen.getByRole("button", { name: "Tokens" }));

    await waitFor(() => {
      expect(getTokenUsage).toHaveBeenCalledTimes(1);
    });
    expect(screen.getByText("Text generation")).toBeInTheDocument();
    expect(screen.getByText("Image generation")).toBeInTheDocument();
  });

  it("switches to Cohorts tab and replaces controls with the months selector", async () => {
    const user = userEvent.setup();
    getLtvSummary.mockResolvedValue(makeLtv());
    renderScreen();

    await user.click(screen.getByRole("button", { name: "Cohorts" }));

    await waitFor(() => {
      expect(getLtvSummary).toHaveBeenCalledWith({ months: 6 });
    });
    expect(screen.getByLabelText(/Lookback months/i)).toBeInTheDocument();
    expect(screen.getByText("Monthly cohorts")).toBeInTheDocument();
  });

  it("re-fetches revenue when the group_by selector changes", async () => {
    const user = userEvent.setup();
    const next = makeRevenue({ group_by: "week", total_purchases: 99 });
    getRevenueSummary.mockResolvedValue(next);
    renderScreen();

    await user.selectOptions(screen.getByLabelText(/Group by/i), "week");

    await waitFor(() => {
      expect(getRevenueSummary).toHaveBeenCalledTimes(1);
    });
    expect(getRevenueSummary).toHaveBeenCalledWith({
      start_date: "2026-05-01",
      end_date: "2026-05-15",
      group_by: "week",
    });
    await waitFor(() => {
      expect(screen.getByText("99")).toBeInTheDocument();
    });
  });

  it("surfaces 403 errors via the role-aware message", async () => {
    const user = userEvent.setup();
    const { ApiError } = await import("@/lib/api/errors");
    getRevenueSummary.mockRejectedValue(new ApiError(403, "forbidden"));
    renderScreen();

    await user.selectOptions(screen.getByLabelText(/Group by/i), "month");

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/don't have permission/i);
  });
});
