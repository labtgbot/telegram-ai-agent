import type { ReactElement } from "react";
import { NavLink, Outlet } from "react-router-dom";

import { useTranslation } from "@/i18n/useTranslation";
import type { TranslationKey } from "@/i18n";
import { useThemeStore } from "@/store/useThemeStore";

const NAV_ITEMS: ReadonlyArray<{ to: string; key: TranslationKey }> = [
  { to: "/", key: "nav.chat" },
  { to: "/balance", key: "nav.balance" },
  { to: "/profile", key: "nav.profile" },
  { to: "/history", key: "nav.history" },
  { to: "/referral", key: "nav.referral" },
  { to: "/settings", key: "nav.settings" },
];

export function AppLayout(): ReactElement {
  const scheme = useThemeStore((s) => s.scheme);
  const { t } = useTranslation();

  return (
    <div className="flex min-h-screen flex-col bg-tg-bg text-tg-text">
      <header className="sticky top-0 z-10 border-b border-tg-separator bg-tg-header px-4 py-3">
        <div className="flex items-center justify-between">
          <h1 className="text-base font-semibold">Telegram AI Agent</h1>
          <span
            className="text-xs uppercase tracking-wide text-tg-hint"
            data-testid="active-scheme"
          >
            {scheme}
          </span>
        </div>
      </header>

      <main className="flex-1 px-4 py-4">
        <Outlet />
      </main>

      <nav className="sticky bottom-0 border-t border-tg-separator bg-tg-header">
        <ul className="flex">
          {NAV_ITEMS.map((item) => (
            <li key={item.to} className="flex-1">
              <NavLink
                to={item.to}
                end={item.to === "/"}
                className={({ isActive }) =>
                  `block px-2 py-3 text-center text-xs transition-colors ${
                    isActive ? "text-tg-link" : "text-tg-hint hover:text-tg-text"
                  }`
                }
              >
                {t(item.key)}
              </NavLink>
            </li>
          ))}
        </ul>
      </nav>
    </div>
  );
}
