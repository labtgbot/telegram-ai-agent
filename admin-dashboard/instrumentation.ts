/**
 * Next.js instrumentation hook.
 *
 * Loads the appropriate Sentry init file based on the runtime. Sentry itself
 * is DSN-gated inside those files, so this register call is safe in all
 * environments — it does nothing when no DSN is configured.
 */
export async function register(): Promise<void> {
  if (process.env.NEXT_RUNTIME === "nodejs") {
    await import("./sentry.server.config");
  }
  if (process.env.NEXT_RUNTIME === "edge") {
    await import("./sentry.edge.config");
  }
}
