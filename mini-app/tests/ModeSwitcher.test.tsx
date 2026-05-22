import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

import { ModeSwitcher } from "@/components/chat/ModeSwitcher";

describe("ModeSwitcher", () => {
  it("renders the three supported modes", () => {
    render(<ModeSwitcher value="basic" onChange={() => undefined} />);
    expect(screen.getByTestId("mode-basic")).toBeInTheDocument();
    expect(screen.getByTestId("mode-advanced")).toBeInTheDocument();
    expect(screen.getByTestId("mode-autonomous_agent")).toBeInTheDocument();
  });

  it("calls onChange with the picked mode", () => {
    const onChange = vi.fn();
    render(<ModeSwitcher value="basic" onChange={onChange} />);
    fireEvent.click(screen.getByTestId("mode-advanced"));
    expect(onChange).toHaveBeenCalledWith("advanced");
  });

  it("marks the active mode with aria-checked=true", () => {
    render(<ModeSwitcher value="advanced" onChange={() => undefined} />);
    expect(screen.getByTestId("mode-advanced")).toHaveAttribute(
      "aria-checked",
      "true",
    );
    expect(screen.getByTestId("mode-basic")).toHaveAttribute(
      "aria-checked",
      "false",
    );
  });
});
