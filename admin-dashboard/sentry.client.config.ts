/**
 * Browser-side Sentry init for the admin dashboard.
 *
 * Sentry is gated on `NEXT_PUBLIC_SENTRY_DSN`. When empty (the default in
 * local development), this file is a no-op so the bundle still loads without
 * shipping any events.
 */
import * as Sentry from "@sentry/nextjs";

const dsn = (process.env.NEXT_PUBLIC_SENTRY_DSN ?? "").trim();

if (dsn) {
  Sentry.init({
    dsn,
    environment:
      (process.env.NEXT_PUBLIC_SENTRY_ENVIRONMENT ?? "").trim() ||
      process.env.NODE_ENV,
    release: (process.env.NEXT_PUBLIC_SENTRY_RELEASE ?? "").trim() || undefined,
    tracesSampleRate: parseRate(
      process.env.NEXT_PUBLIC_SENTRY_TRACES_SAMPLE_RATE,
      0.1,
    ),
    replaysSessionSampleRate: parseRate(
      process.env.NEXT_PUBLIC_SENTRY_REPLAYS_SESSION_SAMPLE_RATE,
      0,
    ),
    replaysOnErrorSampleRate: parseRate(
      process.env.NEXT_PUBLIC_SENTRY_REPLAYS_ON_ERROR_SAMPLE_RATE,
      0,
    ),
    integrations: [
      Sentry.replayIntegration({ maskAllText: true, blockAllMedia: true }),
    ],
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
