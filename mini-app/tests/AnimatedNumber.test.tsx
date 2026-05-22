import { render, screen, act } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AnimatedNumber } from "@/components/billing/AnimatedNumber";

describe("AnimatedNumber", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    let now = 0;
    vi.spyOn(performance, "now").mockImplementation(() => now);
    vi.spyOn(globalThis, "requestAnimationFrame").mockImplementation(
      (cb: FrameRequestCallback) => {
        now += 16;
        return setTimeout(() => cb(now), 16) as unknown as number;
      },
    );
    vi.spyOn(globalThis, "cancelAnimationFrame").mockImplementation((id) => {
      clearTimeout(id as unknown as ReturnType<typeof setTimeout>);
    });
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("renders initial value immediately", () => {
    render(<AnimatedNumber value={1234} data-testid="n" />);
    const el = screen.getByTestId("n");
    expect(el.dataset.value).toBe("1234");
    expect(el.textContent).toBe("1 234");
  });

  it("exposes the target value via data-value before animation settles", () => {
    const { rerender } = render(<AnimatedNumber value={100} data-testid="n" />);
    rerender(<AnimatedNumber value={500} data-testid="n" />);
    expect(screen.getByTestId("n").dataset.value).toBe("500");
  });

  it("tweens towards the new value over the duration", () => {
    const { rerender } = render(
      <AnimatedNumber value={0} data-testid="n" durationMs={100} />,
    );
    rerender(<AnimatedNumber value={1000} data-testid="n" durationMs={100} />);

    act(() => {
      vi.advanceTimersByTime(200);
    });

    expect(screen.getByTestId("n").textContent).toBe("1 000");
  });
});
