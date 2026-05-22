import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ReferralLink } from "@/components/billing/ReferralLink";

const DATA = {
  referral_code: "abc123",
  referral_link: "https://t.me/bot?start=abc123",
  referrals_count: 0,
  bonus_tokens_earned: 0,
};

describe("ReferralLink", () => {
  it("renders the referral link and code", () => {
    render(<ReferralLink data={DATA} isLoading={false} error={null} />);
    expect(screen.getByTestId("referral-input")).toHaveValue(DATA.referral_link);
    expect(screen.getByText(DATA.referral_code)).toBeInTheDocument();
  });

  it("copies the link to the clipboard when the copy button is clicked", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(globalThis.navigator, "clipboard", {
      configurable: true,
      value: { writeText },
    });

    render(<ReferralLink data={DATA} isLoading={false} error={null} />);
    await userEvent.click(screen.getByTestId("referral-copy"));

    expect(writeText).toHaveBeenCalledWith(DATA.referral_link);
    await waitFor(() => {
      expect(screen.getByTestId("referral-copy")).toHaveTextContent("Скопировано");
    });
  });

  it("shows an error state", () => {
    render(<ReferralLink data={undefined} isLoading={false} error={new Error("oops")} />);
    expect(screen.getByTestId("referral-error")).toHaveTextContent("oops");
  });
});
