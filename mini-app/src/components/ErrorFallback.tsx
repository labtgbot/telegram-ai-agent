import type { ReactElement } from "react";

import { Button } from "@/components/Button";

interface ErrorFallbackProps {
  title: string;
  message: string;
  actionLabel: string;
  onAction: () => void;
  testId?: string;
}

export function ErrorFallback({
  title,
  message,
  actionLabel,
  onAction,
  testId = "error-fallback",
}: ErrorFallbackProps): ReactElement {
  return (
    <div
      className="flex min-h-[60vh] items-center justify-center px-4 py-8"
      data-testid={testId}
      role="alert"
    >
      <section className="w-full max-w-sm rounded-tg border border-tg-separator bg-tg-section-bg p-5 text-center shadow-tg">
        <h2 className="text-lg font-semibold text-tg-text">{title}</h2>
        <p className="mt-2 text-sm leading-6 text-tg-hint">{message}</p>
        <Button className="mt-4 w-full" onClick={onAction}>
          {actionLabel}
        </Button>
      </section>
    </div>
  );
}
