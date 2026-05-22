import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { BalanceCard } from "@/components/billing/BalanceCard";
import type { Balance } from "@/types/billing";

describe("BalanceCard", () => {
  it("renders the balance and a premium badge when active", () => {
    const balance: Balance = {
      token_balance: 1500,
      is_premium: true,
      premium_expires_at: "2030-01-15T00:00:00Z",
      daily_bonus_available: false,
    };
    render(<BalanceCard balance={balance} isLoading={false} error={null} />);

    expect(screen.getByTestId("balance").dataset.value).toBe("1500");
    expect(screen.getByTestId("premium-badge")).toHaveTextContent(/Premium/);
    expect(screen.queryByTestId("daily-bonus-badge")).toBeNull();
  });

  it("shows the daily bonus badge when available", () => {
    const balance: Balance = {
      token_balance: 200,
      is_premium: false,
      premium_expires_at: null,
      daily_bonus_available: true,
    };
    render(<BalanceCard balance={balance} isLoading={false} error={null} />);

    expect(screen.getByTestId("daily-bonus-badge")).toHaveTextContent(
      /ежедневный бонус/i,
    );
    expect(screen.queryByTestId("premium-badge")).toBeNull();
  });

  it("renders an error state", () => {
    render(
      <BalanceCard
        balance={undefined}
        isLoading={false}
        error={new Error("network down")}
      />,
    );
    expect(screen.getByTestId("balance-error")).toHaveTextContent("network down");
  });

  it("shows the loading hint when refetching", () => {
    const balance: Balance = {
      token_balance: 0,
      is_premium: false,
      premium_expires_at: null,
      daily_bonus_available: false,
    };
    render(<BalanceCard balance={balance} isLoading={true} error={null} />);
    expect(screen.getByTestId("balance-loading")).toBeInTheDocument();
  });
});
