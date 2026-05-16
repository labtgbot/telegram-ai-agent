/**
 * Lightweight skeleton rendered while a lazy-loaded route chunk is in
 * flight (issue #36 — code-splitting via `React.lazy` + `Suspense`).
 *
 * Kept intentionally tiny so the *fallback* itself never contributes to
 * the LCP budget: pure CSS, no images, no third-party fonts.
 */
export function RouteFallback(): JSX.Element {
  return (
    <div
      aria-busy="true"
      aria-live="polite"
      className="space-y-3 p-4"
      data-testid="route-fallback"
    >
      <div className="h-6 w-1/3 animate-pulse rounded bg-tg-section-bg" />
      <div className="h-24 w-full animate-pulse rounded-tg bg-tg-section-bg" />
      <div className="h-24 w-full animate-pulse rounded-tg bg-tg-section-bg" />
    </div>
  );
}
