import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { Button } from "@/components/Button";

describe("Button", () => {
  it("renders children and calls onClick", async () => {
    const onClick = vi.fn();
    render(<Button onClick={onClick}>Buy tokens</Button>);

    const btn = screen.getByRole("button", { name: "Buy tokens" });
    await userEvent.click(btn);
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it("applies destructive variant class", () => {
    render(<Button variant="destructive">Cancel</Button>);
    const btn = screen.getByRole("button", { name: "Cancel" });
    expect(btn.className).toContain("bg-tg-destructive");
  });

  it("respects the disabled prop", () => {
    render(<Button disabled>Disabled</Button>);
    expect(screen.getByRole("button", { name: "Disabled" })).toBeDisabled();
  });
});
