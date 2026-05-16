import { useEffect } from "react";

import { useThemeStore } from "@/store/useThemeStore";
import { initTelegramWebApp, WebApp } from "@/services/telegram";
import type { TelegramColorScheme, TelegramThemeParams } from "@/types/telegram";

/**
 * Initialise Telegram WebApp on mount and subscribe to live theme changes.
 *
 * Telegram fires `themeChanged` whenever the user switches between light
 * and dark in the host app — re-apply the theme params so CSS variables
 * stay in sync.
 */
export function useTelegramBootstrap(): void {
  const setTheme = useThemeStore((s) => s.setTheme);

  useEffect(() => {
    const { scheme, themeParams } = initTelegramWebApp();
    setTheme(scheme, themeParams);

    const onThemeChanged = (): void => {
      const next: TelegramColorScheme = WebApp.colorScheme === "dark" ? "dark" : "light";
      const params = (WebApp.themeParams ?? {}) as TelegramThemeParams;
      setTheme(next, params);
    };

    try {
      WebApp.onEvent("themeChanged", onThemeChanged);
    } catch {
      /* outside of Telegram: ignore */
    }

    return () => {
      try {
        WebApp.offEvent("themeChanged", onThemeChanged);
      } catch {
        /* ignore */
      }
    };
  }, [setTheme]);
}
