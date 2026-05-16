import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { DailyBonusCard } from "@/components/DailyBonusCard";
import { useSettingsStore } from "@/store/useSettingsStore";
import { useUserStore } from "@/store/useUserStore";
import type { DailyBonusClaim, DailyBonusStatus } from "@/types/profile";

vi.mock("@/services/userApi", () => ({
  userApi: {
    getDailyBonusStatus: vi.fn(),
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

vi.mock("@/services/telegram", () => ({
  WebApp: {},
  getInitData: () => "",
}));

import { ApiError, userApi } from "@/services/userApi";

const getStatusMock = vi.mocked(userApi.getDailyBonusStatus);
const claimMock = vi.mocked(userApi.claimDailyBonus);

function status(overrides: Partial<DailyBonusStatus> = {}): DailyBonusStatus {
  return {
    available: true,
    enabled: true,
    streak_day: 0,
    next_amount: 10,
    last_claim_date: null,
    next_available_at: "2026-05-17T00:00:00+00:00",
    amounts: [10, 12, 15, 20],
    ...overrides,
  };
}

function claim(overrides: Partial<DailyBonusClaim> = {}): DailyBonusClaim {
  return {
    amount: 10,
    streak_day: 1,
    new_balance: 260,
    transaction_id: 1,
    claim_date: "2026-05-16",
    next_available_at: "2026-05-17T00:00:00+00:00",
    ...overrides,
  };
}

beforeEach(() => {
  useUserStore.getState().reset();
  useSettingsStore.getState().reset();
  getStatusMock.mockReset();
  claimMock.mockReset();
  getStatusMock.mockResolvedValue(status());
});

describe("DailyBonusCard", () => {
  it("renders the claim button with the next reward amount", async () => {
    render(<DailyBonusCard />);
    await waitFor(() => expect(getStatusMock).toHaveBeenCalled());

    const button = await screen.findByTestId("daily-bonus-claim");
    expect(button).toHaveTextContent("Claim 10 tokens");
    expect(screen.getByTestId("daily-bonus-ladder")).toHaveTextContent("10 → 12 → 15 → 20");
  });

  it("credits the bonus on click and updates the store balance", async () => {
    claimMock.mockResolvedValueOnce(claim({ amount: 10, new_balance: 260, streak_day: 1 }));

    render(<DailyBonusCard />);
    await userEvent.click(await screen.findByTestId("daily-bonus-claim"));

    await waitFor(() =>
      expect(screen.getByTestId("daily-bonus-claimed")).toHaveTextContent("+10 tokens"),
    );
    expect(useUserStore.getState().balance).toBe(260);
    expect(screen.getByTestId("daily-bonus-cooldown")).toHaveTextContent("00:00 UTC");
  });

  it("falls back to the cooldown state when status reports not-available", async () => {
    getStatusMock.mockResolvedValueOnce(
      status({ available: false, streak_day: 3, next_amount: 20 }),
    );

    render(<DailyBonusCard />);
    expect(await screen.findByTestId("daily-bonus-cooldown")).toBeInTheDocument();
    expect(screen.queryByTestId("daily-bonus-claim")).not.toBeInTheDocument();
  });

  it("shows the disabled state when the loop is paused", async () => {
    getStatusMock.mockResolvedValueOnce(status({ enabled: false, available: false }));
    render(<DailyBonusCard />);
    expect(await screen.findByTestId("daily-bonus-disabled")).toBeInTheDocument();
  });

  it("re-reads status when the claim returns 409 (already claimed elsewhere)", async () => {
    claimMock.mockRejectedValueOnce(new ApiError("already_claimed", 409, null));
    getStatusMock.mockResolvedValueOnce(status());
    getStatusMock.mockResolvedValueOnce(status({ available: false }));

    render(<DailyBonusCard />);
    await userEvent.click(await screen.findByTestId("daily-bonus-claim"));

    expect(await screen.findByTestId("daily-bonus-cooldown")).toBeInTheDocument();
    expect(getStatusMock).toHaveBeenCalledTimes(2);
  });

  it("surfaces a retry button when the initial status load fails", async () => {
    getStatusMock.mockReset();
    getStatusMock.mockRejectedValueOnce(new Error("boom"));

    render(<DailyBonusCard />);
    const retry = await screen.findByRole("button", { name: "Retry" });

    getStatusMock.mockResolvedValueOnce(status());
    await userEvent.click(retry);
    expect(await screen.findByTestId("daily-bonus-claim")).toBeInTheDocument();
  });
});
