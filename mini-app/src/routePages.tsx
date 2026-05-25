import { lazy } from "react";

export const HomePage = lazy(() => import("@/pages/HomePage").then((m) => ({ default: m.HomePage })));
export const BalancePage = lazy(() =>
  import("@/pages/BalancePage").then((m) => ({ default: m.BalancePage })),
);
export const HistoryPage = lazy(() =>
  import("@/pages/HistoryPage").then((m) => ({ default: m.HistoryPage })),
);
export const NotFoundPage = lazy(() =>
  import("@/pages/NotFoundPage").then((m) => ({ default: m.NotFoundPage })),
);
export const ProfilePage = lazy(() =>
  import("@/pages/ProfilePage").then((m) => ({ default: m.ProfilePage })),
);
export const ReferralPage = lazy(() =>
  import("@/pages/ReferralPage").then((m) => ({ default: m.ReferralPage })),
);
export const SettingsPage = lazy(() =>
  import("@/pages/SettingsPage").then((m) => ({ default: m.SettingsPage })),
);
