import { lazy, Suspense } from "react";
import { createBrowserRouter } from "react-router-dom";

import { AppLayout } from "@/layouts/AppLayout";
import { ChatPage } from "@/pages/ChatPage";
import { RouteFallback } from "@/components/RouteFallback";

// Code-splitting per route keeps the initial bundle small (issue #36
// targets < 200 KB gzipped main chunk). The Telegram WebView prefers a
// single fast paint over an instantly-interactive deeper navigation,
// and Suspense serves a skeleton in the < 100 ms range it takes for
// the chunk to arrive from the CDN.
const HomePage = lazy(() =>
  import("@/pages/HomePage").then((m) => ({ default: m.HomePage })),
);
const BalancePage = lazy(() =>
  import("@/pages/BalancePage").then((m) => ({ default: m.BalancePage })),
);
const HistoryPage = lazy(() =>
  import("@/pages/HistoryPage").then((m) => ({ default: m.HistoryPage })),
);
const NotFoundPage = lazy(() =>
  import("@/pages/NotFoundPage").then((m) => ({ default: m.NotFoundPage })),
);
const ProfilePage = lazy(() =>
  import("@/pages/ProfilePage").then((m) => ({ default: m.ProfilePage })),
);
const ReferralPage = lazy(() =>
  import("@/pages/ReferralPage").then((m) => ({ default: m.ReferralPage })),
);
const SettingsPage = lazy(() =>
  import("@/pages/SettingsPage").then((m) => ({ default: m.SettingsPage })),
);

const withSuspense = (element: JSX.Element): JSX.Element => (
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
