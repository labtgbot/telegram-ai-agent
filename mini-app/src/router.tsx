import type { ReactElement } from "react";
import { Suspense } from "react";
import { createBrowserRouter } from "react-router-dom";

import { AppLayout } from "@/layouts/AppLayout";
import { ChatPage } from "@/pages/ChatPage";
import { RouteFallback } from "@/components/RouteFallback";
import {
  BalancePage,
  HistoryPage,
  HomePage,
  NotFoundPage,
  ProfilePage,
  ReferralPage,
  SettingsPage,
} from "@/routePages";

// Code-splitting per route keeps the initial bundle small (issue #36
// targets < 200 KB gzipped main chunk). The Telegram WebView prefers a
// single fast paint over an instantly-interactive deeper navigation,
// and Suspense serves a skeleton in the < 100 ms range it takes for
// the chunk to arrive from the CDN.
const withSuspense = (element: ReactElement): ReactElement => (
  <Suspense fallback={<RouteFallback />}>{element}</Suspense>
);

export const router = createBrowserRouter([
  {
    path: "/",
    element: <AppLayout />,
    children: [
      { index: true, element: <ChatPage /> },
      { path: "home", element: withSuspense(<HomePage />) },
      { path: "balance", element: withSuspense(<BalancePage />) },
      { path: "profile", element: withSuspense(<ProfilePage />) },
      { path: "history", element: withSuspense(<HistoryPage />) },
      { path: "referral", element: withSuspense(<ReferralPage />) },
      { path: "settings", element: withSuspense(<SettingsPage />) },
      { path: "*", element: withSuspense(<NotFoundPage />) },
    ],
  },
]);
