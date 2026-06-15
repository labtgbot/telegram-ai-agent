import type { ErrorInfo } from "react";

import { Sentry } from "@/lib/sentry";

export type UiErrorSource = "react-render" | "router";

export function reportUiError(error: unknown, source: UiErrorSource, errorInfo?: ErrorInfo): void {
  console.error(`[mini-app] ${source} error`, error, errorInfo ?? "");
  Sentry.captureException(error);
}
