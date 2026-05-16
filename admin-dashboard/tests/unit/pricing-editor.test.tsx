import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { PricingEditor } from "@/components/admin-pricing/pricing-editor";
import type {
  PricingConfig,
  PricingHistoryResponse,
} from "@/lib/admin-pricing/types";

const getPricingHistory = vi.fn();
const postPricingUpdate = vi.fn();

vi.mock("@/lib/admin-pricing/browser", () => ({
  getPricingHistory: (...args: unknown[]) => getPricingHistory(...args),
  postPricingUpdate: (...args: unknown[]) => postPricingUpdate(...args),
}));

function makeConfig(overrides: Partial<PricingConfig> = {}): PricingConfig {
  return {
    packages: [
      {
        code: "starter",
        title: "Starter",
        description: "Try it out",
        tokens: 1_000,
        stars: 200,
        discount: 0,
        is_subscription: false,
      },
      {
        code: "pro_monthly",
        title: "Pro monthly",
        description: "Subscription",
        tokens: 50_000,
        stars: 500,
        discount: 10,
        is_subscription: true,
      },
    ],
    global_discount: 0,
    seasonal_promo: 0,
    first_purchase_bonus: 0,
    referral_bonus: 0,
    daily_bonus: 0,
    currency_rate: 0.013,
    limits: {
      max_discount_percent: 95,
      max_tokens_per_package: 10_000_000,
      max_stars_per_package: 1_000_000,
      max_bonus_tokens: 100_000,
    },
    ...overrides,
  };
}

const emptyHistory: PricingHistoryResponse = {
  items: [],
  total: 0,
  page: 1,
  limit: 25,
  has_more: false,
};

describe("<PricingEditor />", () => {
  beforeEach(() => {
    getPricingHistory.mockReset();
    postPricingUpdate.mockReset();
    getPricingHistory.mockResolvedValue(emptyHistory);
  });
  afterEach(() => cleanup());

  it("shows current packages and the empty change-history copy", () => {
    render(
      <PricingEditor initialConfig={makeConfig()} initialHistory={emptyHistory} canEdit />,
    );
    expect(screen.getByRole("heading", { name: /packages/i, level: 2 })).toBeInTheDocument();
    expect(screen.getByText(/Starter/)).toBeInTheDocument();
    expect(screen.getByText(/Pro monthly/)).toBeInTheDocument();
    expect(screen.getByText(/No changes recorded yet\./i)).toBeInTheDocument();
  });

  it("recomputes effective price preview when discount fields change", async () => {
    const user = userEvent.setup();
    render(
      <PricingEditor initialConfig={makeConfig()} initialHistory={emptyHistory} canEdit />,
    );

    const globalInput = screen.getByLabelText(/Global discount %/i);
    await user.clear(globalInput);
    await user.type(globalInput, "50");

    // Starter: 200 stars · 50% off → 100 ⭐
    await waitFor(() => {
      expect(screen.getAllByText(/100 ⭐/).length).toBeGreaterThan(0);
    });
  });

  it("hides the save bar in read-only mode", () => {
    render(
      <PricingEditor
        initialConfig={makeConfig()}
        initialHistory={emptyHistory}
        canEdit={false}
      />,
    );
    expect(screen.queryByRole("button", { name: /Save changes/i })).toBeNull();
  });

  it("requires confirmation before saving and posts the diff", async () => {
    const user = userEvent.setup();
    postPricingUpdate.mockResolvedValue({
      config: makeConfig({ global_discount: 25 }),
      diff: { globals: { global_discount: { before: 0, after: 25 } } },
      audit_log_id: 7,
    });

    render(
      <PricingEditor initialConfig={makeConfig()} initialHistory={emptyHistory} canEdit />,
    );

    const globalInput = screen.getByLabelText(/Global discount %/i);
    await user.clear(globalInput);
    await user.type(globalInput, "25");

    const saveButton = await screen.findByRole("button", { name: /Save changes/i });
    await user.click(saveButton);

    const dialog = await screen.findByRole("dialog", { name: /Confirm pricing changes/i });
    expect(within(dialog).getByText(/Global discount/)).toBeInTheDocument();

    await user.click(within(dialog).getByRole("button", { name: /Apply changes/i }));

    await waitFor(() => {
      expect(postPricingUpdate).toHaveBeenCalledTimes(1);
    });
    expect(postPricingUpdate).toHaveBeenCalledWith({ global_discount: 25 });
    await waitFor(() => {
      expect(screen.getByRole("status")).toHaveTextContent(/audit log #7/i);
    });
  });

  it("blocks save when validation fails (e.g. discount over the limit)", async () => {
    const user = userEvent.setup();
    render(
      <PricingEditor initialConfig={makeConfig()} initialHistory={emptyHistory} canEdit />,
    );

    const globalInput = screen.getByLabelText(/Global discount %/i);
    await user.clear(globalInput);
    await user.type(globalInput, "200");

    const saveButton = await screen.findByRole("button", { name: /Save changes/i });
    expect(saveButton).toBeDisabled();
  });
});
