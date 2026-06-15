import type { ErrorInfo, ReactElement, ReactNode } from "react";
import { Component } from "react";

import { ErrorFallback } from "@/components/ErrorFallback";
import { useTranslation } from "@/i18n/useTranslation";
import { reportUiError } from "@/lib/errorReporting";

interface AppErrorBoundaryProps {
  children: ReactNode;
  onReload?: () => void;
}

interface AppErrorBoundaryState {
  hasError: boolean;
}

function reloadPage(): void {
  window.location.reload();
}

function AppErrorBoundaryFallback({ onReload }: { onReload: () => void }): ReactElement {
  const { t } = useTranslation();
  return (
    <ErrorFallback
      actionLabel={t("errors.reload")}
      message={t("errors.appBody")}
      onAction={onReload}
      testId="app-error-fallback"
      title={t("errors.appTitle")}
    />
  );
}

export class AppErrorBoundary extends Component<AppErrorBoundaryProps, AppErrorBoundaryState> {
  state: AppErrorBoundaryState = { hasError: false };

  static getDerivedStateFromError(): AppErrorBoundaryState {
    return { hasError: true };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo): void {
    reportUiError(error, "react-render", errorInfo);
  }

  render(): ReactNode {
    if (this.state.hasError) {
      return <AppErrorBoundaryFallback onReload={this.props.onReload ?? reloadPage} />;
    }

    return this.props.children;
  }
}
