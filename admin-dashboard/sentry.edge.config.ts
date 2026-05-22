/**
 * Edge runtime Sentry init for the admin dashboard (middleware + edge routes).
 *
 * DSN-gated to remain a no-op locally and in tests.
 */
import * as Sentry from "@sentry/nextjs";

const dsn = (
  process.env.SENTRY_DSN ??
  process.env.NEXT_PUBLIC_SENTRY_DSN ??
  ""
).trim();

if (dsn) {
  Sentry.init({
    dsn,
    environment:
      (process.env.SENTRY_ENVIRONMENT ?? "").trim() ||
      (process.env.NEXT_PUBLIC_SENTRY_ENVIRONMENT ?? "").trim() ||
      process.env.NODE_ENV,
    release:
      (process.env.SENTRY_RELEASE ?? "").trim() ||
      (process.env.NEXT_PUBLIC_SENTRY_RELEASE ?? "").trim() ||
      undefined,
    tracesSampleRate: parseRate(process.env.SENTRY_TRACES_SAMPLE_RATE, 0.1),
    sendDefaultPii: false,
  });
  Sentry.setTag("service", "admin-dashboard");
  Sentry.setTag("runtime", "edge");
}

function parseRate(raw: string | undefined, fallback: number): number {
  if (raw === undefined || raw === "") return fallback;
  const value = Number.parseFloat(raw);
  if (Number.isNaN(value) || value < 0 || value > 1) return fallback;
  return value;
}
