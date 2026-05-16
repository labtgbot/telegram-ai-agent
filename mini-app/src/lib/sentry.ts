/**
 * Sentry initialisation for the Telegram Mini App.
 *
 * Reads the DSN from `VITE_SENTRY_DSN`. When the variable is empty (the
 * default for local development), this module is a no-op so the bundle still
 * loads and runs but no events are shipped to Sentry.
 */
import * as Sentry from "@sentry/react";

let initialised = false;

export function initSentry(): boolean {
  if (initialised) {
    return false;
  }

  const dsn = (import.meta.env.VITE_SENTRY_DSN ?? "").trim();
  if (!dsn) {
    return false;
  }

  const environment =
    (import.meta.env.VITE_SENTRY_ENVIRONMENT ?? "").trim() ||
    (import.meta.env.MODE ?? "production");
  const release = (import.meta.env.VITE_SENTRY_RELEASE ?? "").trim() || undefined;
  const tracesSampleRate = parseSampleRate(
    import.meta.env.VITE_SENTRY_TRACES_SAMPLE_RATE,
    0.1,
  );
  const replaysSessionSampleRate = parseSampleRate(
    import.meta.env.VITE_SENTRY_REPLAYS_SESSION_SAMPLE_RATE,
    0,
  );
  const replaysOnErrorSampleRate = parseSampleRate(
    import.meta.env.VITE_SENTRY_REPLAYS_ON_ERROR_SAMPLE_RATE,
    0,
  );

  Sentry.init({
    dsn,
    environment,
    release,
    tracesSampleRate,
    replaysSessionSampleRate,
    replaysOnErrorSampleRate,
    integrations: [
      Sentry.browserTracingIntegration(),
      Sentry.replayIntegration({ maskAllText: true, blockAllMedia: true }),
    ],
    sendDefaultPii: false,
  });

  Sentry.setTag("service", "mini-app");
  initialised = true;
  return true;
}

function parseSampleRate(raw: string | undefined, fallback: number): number {
  if (raw === undefined || raw === "") {
    return fallback;
  }
  const value = Number.parseFloat(raw);
  if (Number.isNaN(value) || value < 0 || value > 1) {
    return fallback;
  }
  return value;
}

export { Sentry };
