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
    <div className="error-fallback" data-testid={testId} role="alert">
      <section className="error-fallback__panel">
        <h2 className="error-fallback__title">{title}</h2>
        <p className="error-fallback__message">{message}</p>
        <Button className="error-fallback__button" onClick={onAction}>
          {actionLabel}
        </Button>
      </section>
    </div>
  );
}
