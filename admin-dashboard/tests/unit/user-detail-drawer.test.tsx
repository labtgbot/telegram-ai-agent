import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { UserDetailDrawer } from "@/components/admin-users/user-detail-drawer";
import type { UserStatsResponse } from "@/lib/admin-users/types";

const push = vi.fn();
let currentParams = new URLSearchParams();
const getUserStats = vi.fn();
const addTokens = vi.fn();
const banUser = vi.fn();
const unbanUser = vi.fn();
const sendUserMessage = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
  useSearchParams: () => currentParams,
}));

vi.mock("@/lib/admin-users/browser", () => ({
  getUserStats: (...args: unknown[]) => getUserStats(...args),
  addTokens: (...args: unknown[]) => addTokens(...args),
  banUser: (...args: unknown[]) => banUser(...args),
  unbanUser: (...args: unknown[]) => unbanUser(...args),
  sendUserMessage: (...args: unknown[]) => sendUserMessage(...args),
}));

function fakeStats(overrides: Partial<UserStatsResponse> = {}): UserStatsResponse {
  return {
    user: {
      id: 42,
      telegram_id: 1234,
      username: "alice",
      first_name: "Alice",
      last_name: null,
      language_code: "en",
      role: "user",
      is_premium: false,
      is_banned: false,
      ban_reason: null,
      banned_until: null,
      token_balance: 100,
      total_tokens_purchased: 0,
      total_tokens_spent: 10,
      total_requests: 5,
      referral_code: "AU-42",
      referred_by: null,
      created_at: "2026-05-01T00:00:00Z",
      last_active_at: "2026-05-15T00:00:00Z",
      last_login_at: null,
    },
    transactions_total: 0,
    recent_transactions: [],
    services_usage: [],
    referrals_count: 0,
    recent_referrals: [],
    ...overrides,
  };
}

describe("<UserDetailDrawer />", () => {
  beforeEach(() => {
    push.mockReset();
    getUserStats.mockReset();
    addTokens.mockReset();
    banUser.mockReset();
    unbanUser.mockReset();
    sendUserMessage.mockReset();
    currentParams = new URLSearchParams("user=42");
  });
  afterEach(() => cleanup());

  it("returns null when no userId is provided", () => {
    const { container } = render(<UserDetailDrawer userId={undefined} />);
    expect(container.firstChild).toBeNull();
  });

  it("fetches stats on open and renders profile + transactions", async () => {
    getUserStats.mockResolvedValueOnce(fakeStats());
    render(<UserDetailDrawer userId={42} />);
    expect(await screen.findByText("Alice")).toBeInTheDocument();
    expect(screen.getAllByText(/@alice/i).length).toBeGreaterThan(0);
    expect(getUserStats).toHaveBeenCalledWith(42);
  });

  it("submits add-tokens and re-fetches stats", async () => {
    getUserStats
      .mockResolvedValueOnce(fakeStats())
      .mockResolvedValueOnce(fakeStats({ user: { ...fakeStats().user, token_balance: 200 } }));
    addTokens.mockResolvedValueOnce({ user_id: 42, amount: 100, new_balance: 200, transaction_id: 1 });

    const user = userEvent.setup();
    render(<UserDetailDrawer userId={42} />);
    await screen.findByText("Alice");

    await user.type(screen.getByLabelText("Amount"), "100");
    await user.click(screen.getByRole("button", { name: /credit/i }));

    await waitFor(() => {
      expect(addTokens).toHaveBeenCalledWith(42, { amount: 100, reason: "manual grant" });
    });
    expect(getUserStats).toHaveBeenCalledTimes(2);
  });

  it("shows lift-ban control when user is already banned", async () => {
    getUserStats.mockResolvedValueOnce(
      fakeStats({
        user: { ...fakeStats().user, is_banned: true, ban_reason: "spam" },
      }),
    );
    unbanUser.mockResolvedValueOnce(fakeStats().user);

    const user = userEvent.setup();
    render(<UserDetailDrawer userId={42} />);
    await screen.findByText("Alice");

    await user.click(screen.getByRole("button", { name: /lift ban/i }));
    await waitFor(() => expect(unbanUser).toHaveBeenCalledWith(42));
  });

  it("surfaces a human error when stats fetch fails", async () => {
    getUserStats.mockRejectedValueOnce(new Error("boom"));
    render(<UserDetailDrawer userId={42} />);
    expect(await screen.findByText(/boom/i)).toBeInTheDocument();
  });
});
