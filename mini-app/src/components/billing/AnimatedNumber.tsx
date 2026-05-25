import type { ReactElement } from "react";
import { useEffect, useRef, useState } from "react";

interface AnimatedNumberProps {
  /** Target value to display.  When it changes, the component tweens. */
  value: number;
  /** Animation duration in ms.  Defaults to 800 ms. */
  durationMs?: number;
  /** Optional className passed through to the wrapper. */
  className?: string;
  /** Optional formatter (e.g. for thousands separators).  Defaults to `Intl.NumberFormat`. */
  format?: (value: number) => string;
  /** Optional test id propagated to the wrapper. */
  "data-testid"?: string;
}

const DEFAULT_FORMATTER = new Intl.NumberFormat("ru-RU");

function easeOutCubic(t: number): number {
  return 1 - (1 - t) ** 3;
}

/**
 * Animated integer counter.  Tweens from the previously rendered value to
 * the new `value` using `requestAnimationFrame` with an ease-out curve.
 *
 * The component renders the live value as text and exposes the final
 * value via the `data-value` attribute so tests can assert on the target
 * without waiting for the animation to settle.
 */
export function AnimatedNumber({
  value,
  durationMs = 800,
  className,
  format,
  "data-testid": testId,
}: AnimatedNumberProps): ReactElement {
  const [display, setDisplay] = useState(value);
  const fromRef = useRef(value);
  const rafRef = useRef<number | null>(null);

  useEffect(() => {
    if (value === display) {
      fromRef.current = value;
      return undefined;
    }

    const from = fromRef.current;
    const to = value;
    const start = performance.now();

    function tick(now: number): void {
      const elapsed = now - start;
      const progress = Math.min(elapsed / durationMs, 1);
      const eased = easeOutCubic(progress);
      const next = Math.round(from + (to - from) * eased);
      setDisplay(next);
      if (progress < 1) {
        rafRef.current = requestAnimationFrame(tick);
      } else {
        fromRef.current = to;
        rafRef.current = null;
      }
    }

    rafRef.current = requestAnimationFrame(tick);
    return () => {
      if (rafRef.current !== null) {
        cancelAnimationFrame(rafRef.current);
        rafRef.current = null;
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value, durationMs]);

  const formatter = format ?? ((v: number) => DEFAULT_FORMATTER.format(v));
  return (
    <span className={className} data-testid={testId} data-value={value}>
      {formatter(display)}
    </span>
  );
}
