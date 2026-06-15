import type { ReactElement } from "react";
import { RouterProvider } from "react-router-dom";

import { router } from "@/router";
import { useTelegramBootstrap } from "@/hooks/useTelegram";
import { AppErrorBoundary } from "@/components/AppErrorBoundary";
import { ConsentBanner } from "@/components/ConsentBanner";

export function App(): ReactElement {
  useTelegramBootstrap();
  return (
    <AppErrorBoundary>
      <RouterProvider router={router} />
      <ConsentBanner />
    </AppErrorBoundary>
  );
}
