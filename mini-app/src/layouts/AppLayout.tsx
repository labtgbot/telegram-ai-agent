import { NavLink, Outlet } from "react-router-dom";

import { useThemeStore } from "@/store/useThemeStore";

const NAV_ITEMS: Array<{ to: string; label: string }> = [
  { to: "/", label: "Chat" },
  { to: "/balance", label: "Balance" },
  { to: "/settings", label: "Settings" },
];

export function AppLayout(): JSX.Element {
  const scheme = useThemeStore((s) => s.scheme);

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
                  `block px-4 py-3 text-center text-sm transition-colors ${
                    isActive ? "text-tg-link" : "text-tg-hint hover:text-tg-text"
                  }`
                }
              >
                {item.label}
              </NavLink>
            </li>
          ))}
        </ul>
      </nav>
    </div>
  );
}
