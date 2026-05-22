import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { ReferralPage } from "@/pages/ReferralPage";
import { useSettingsStore } from "@/store/useSettingsStore";
import { useUserStore } from "@/store/useUserStore";
import type { ReferralSummary } from "@/types/profile";

vi.mock("@/services/userApi", () => ({
  userApi: {
    getReferralSummary: vi.fn(),
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

const openTelegramLinkMock = vi.fn();

vi.mock("@/services/telegram", () => ({
  WebApp: {
    openTelegramLink: (...args: unknown[]) => openTelegramLinkMock(...args),
  },
  getInitData: () => "",
}));

import { userApi } from "@/services/userApi";

const getReferralMock = vi.mocked(userApi.getReferralSummary);

function summary(overrides: Partial<ReferralSummary> = {}): ReferralSummary {
  return {
    referral_code: "ABCD1234",
    referrals_count: 3,
    bonus_tokens_earned: 300,
    referral_link: "https://t.me/test_bot?start=ABCD1234",
    ...overrides,
  };
}

beforeEach(() => {
  useUserStore.getState().reset();
  useSettingsStore.getState().reset();
  getReferralMock.mockReset();
  getReferralMock.mockResolvedValue(summary());
  openTelegramLinkMock.mockReset();
  Object.assign(navigator, {
    clipboard: { writeText: vi.fn().mockResolvedValue(undefined) },
  });
});

describe("ReferralPage", () => {
  it("renders the referral link, code and stats", async () => {
    render(<ReferralPage />);
    await waitFor(() => expect(getReferralMock).toHaveBeenCalled());

    const linkInput = (await screen.findByTestId("referral-link")) as HTMLInputElement;
    expect(linkInput.value).toBe("https://t.me/test_bot?start=ABCD1234");
    expect(screen.getByTestId("referral-code")).toHaveTextContent("ABCD1234");
    expect(screen.getByTestId("referral-count-row")).toHaveTextContent("3");
    expect(screen.getByTestId("referral-bonus-row")).toHaveTextContent("300");
  });

  it("copies the link to the clipboard and shows a confirmation", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });

    render(<ReferralPage />);
    await waitFor(() => expect(getReferralMock).toHaveBeenCalled());

    await userEvent.click(await screen.findByRole("button", { name: "Copy link" }));
    expect(writeText).toHaveBeenCalledWith("https://t.me/test_bot?start=ABCD1234");
    expect(await screen.findByTestId("referral-copied")).toBeInTheDocument();
  });

  it("opens the Telegram share dialog when the share button is clicked", async () => {
    render(<ReferralPage />);
    await waitFor(() => expect(getReferralMock).toHaveBeenCalled());

    await userEvent.click(await screen.findByRole("button", { name: "Share with friends" }));
    expect(openTelegramLinkMock).toHaveBeenCalledTimes(1);
    const url = openTelegramLinkMock.mock.calls[0]![0] as string;
    expect(url.startsWith("https://t.me/share/url?url=")).toBe(true);
    expect(url).toContain(encodeURIComponent("https://t.me/test_bot?start=ABCD1234"));
  });

  it("shows the empty state when there are no referrals yet", async () => {
    getReferralMock.mockResolvedValueOnce(summary({ referrals_count: 0, bonus_tokens_earned: 0 }));
    render(<ReferralPage />);
    expect(await screen.findByTestId("referral-empty")).toBeInTheDocument();
  });

  it("renders an error state with retry when the API fails", async () => {
    getReferralMock.mockRejectedValueOnce(new Error("boom"));
    render(<ReferralPage />);
    const retry = await screen.findByRole("button", { name: "Retry" });

    getReferralMock.mockResolvedValueOnce(summary());
    await userEvent.click(retry);
    expect(await screen.findByTestId("referral-link")).toBeInTheDocument();
  });
});
