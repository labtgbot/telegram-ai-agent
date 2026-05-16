/**
 * Server-side Sentry init for the admin dashboard (Node runtime).
 *
 * Reads `SENTRY_DSN` (falling back to `NEXT_PUBLIC_SENTRY_DSN`) and is a no-op
 * when the DSN is empty, so local dev does not ship events.
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
}

function parseRate(raw: string | undefined, fallback: number): number {
  if (raw === undefined || raw === "") return fallback;
  const value = Number.parseFloat(raw);
  if (Number.isNaN(value) || value < 0 || value > 1) return fallback;
  return value;
}
