import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { BonusList } from "@/components/billing/BonusList";

describe("BonusList", () => {
  it("marks the daily bonus as available", () => {
    render(<BonusList dailyAvailable={true} hasReferral={true} />);
    const daily = screen.getByTestId("bonus-daily");
    expect(daily).toHaveTextContent("Доступен");
    expect(screen.getByTestId("bonus-referral")).toHaveTextContent("Активна");
    expect(screen.getByTestId("bonus-first-purchase")).toBeInTheDocument();
  });

  it("marks the daily bonus as already claimed", () => {
    render(<BonusList dailyAvailable={false} hasReferral={false} />);
    expect(screen.getByTestId("bonus-daily")).toHaveTextContent("Уже получен");
    expect(screen.getByTestId("bonus-referral")).toHaveTextContent("Скопируйте");
  });
});
