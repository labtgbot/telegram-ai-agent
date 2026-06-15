import type { ReactElement } from "react";
import { useEffect } from "react";
import { useRouteError } from "react-router-dom";

import { ErrorFallback } from "@/components/ErrorFallback";
import { useTranslation } from "@/i18n/useTranslation";
import { reportUiError } from "@/lib/errorReporting";

function reloadPage(): void {
  window.location.reload();
}

export function RouteErrorElement(): ReactElement {
  const error = useRouteError();
  const { t } = useTranslation();

  useEffect(() => {
    reportUiError(error, "router");
  }, [error]);

  return (
    <ErrorFallback
      actionLabel={t("errors.reload")}
      message={t("errors.routeBody")}
      onAction={reloadPage}
      testId="route-error-fallback"
      title={t("errors.routeTitle")}
    />
  );
}
