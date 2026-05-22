import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { PackageGrid } from "@/components/billing/PackageGrid";
import type { PackageItem } from "@/types/billing";

const PACKAGES: PackageItem[] = [
  {
    code: "starter",
    title: "Starter",
    description: "500 tokens",
    tokens: 500,
    stars: 250,
    is_subscription: false,
    subscription_days: 0,
  },
  {
    code: "premium",
    title: "Premium",
    description: "2,000 tokens",
    tokens: 2000,
    stars: 750,
    is_subscription: false,
    subscription_days: 0,
  },
];

describe("PackageGrid", () => {
  it("renders one card per package with title and price", () => {
    render(
      <PackageGrid
        packages={PACKAGES}
        isLoading={false}
        error={null}
        buyingCode={null}
        onBuy={() => undefined}
      />,
    );

    expect(screen.getByTestId("package-card-starter")).toHaveTextContent("Starter");
    expect(screen.getByTestId("package-card-starter")).toHaveTextContent("250");
    expect(screen.getByTestId("package-card-premium")).toHaveTextContent("Premium");
    expect(screen.getByTestId("package-card-premium")).toHaveTextContent("750");
  });

  it("highlights the premium card", () => {
    render(
      <PackageGrid
        packages={PACKAGES}
        isLoading={false}
        error={null}
        buyingCode={null}
        onBuy={() => undefined}
      />,
    );
    expect(screen.getByTestId("package-badge-premium")).toBeInTheDocument();
    expect(screen.queryByTestId("package-badge-starter")).toBeNull();
  });

  it("invokes onBuy when the buy button is clicked", async () => {
    const onBuy = vi.fn();
    render(
      <PackageGrid
        packages={PACKAGES}
        isLoading={false}
        error={null}
        buyingCode={null}
        onBuy={onBuy}
      />,
    );
    await userEvent.click(screen.getByTestId("package-buy-starter"));
    expect(onBuy).toHaveBeenCalledWith("starter");
  });

  it("disables other cards while one is being purchased", () => {
    render(
      <PackageGrid
        packages={PACKAGES}
        isLoading={false}
        error={null}
        buyingCode="starter"
        onBuy={() => undefined}
      />,
    );
    expect(screen.getByTestId("package-buy-starter")).toHaveTextContent("Открываем");
    expect(screen.getByTestId("package-buy-starter")).toBeDisabled();
    expect(screen.getByTestId("package-buy-premium")).toBeDisabled();
  });

  it("shows an error state", () => {
    render(
      <PackageGrid
        packages={undefined}
        isLoading={false}
        error={new Error("boom")}
        buyingCode={null}
        onBuy={() => undefined}
      />,
    );
    expect(screen.getByTestId("packages-error")).toHaveTextContent("boom");
  });
});
