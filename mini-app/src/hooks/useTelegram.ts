import { useEffect } from "react";

import { useThemeStore } from "@/store/useThemeStore";
import { useUserStore } from "@/store/useUserStore";
import type { User } from "@/store/useUserStore";
import { initTelegramWebApp, WebApp } from "@/services/telegram";
import type { TelegramColorScheme, TelegramInitUser, TelegramThemeParams } from "@/types/telegram";

/** Build a `User` shape from Telegram's `initDataUnsafe.user` for instant UI. */
function userFromTelegram(tgUser: TelegramInitUser): User {
  return {
    id: 0,
    telegram_id: tgUser.id,
    username: tgUser.username ?? null,
    first_name: tgUser.first_name ?? null,
    last_name: tgUser.last_name ?? null,
    language_code: tgUser.language_code ?? null,
    role: "user",
    referral_code: "",
    is_premium: Boolean(tgUser.is_premium),
    is_banned: false,
    photo_url: tgUser.photo_url ?? null,
    premium_expires_at: null,
    created_at: null,
    totp_enabled: false,
  };
}

/**
 * Initialise Telegram WebApp on mount and subscribe to live theme changes.
 *
 * Telegram fires `themeChanged` whenever the user switches between light
 * and dark in the host app — re-apply the theme params so CSS variables
 * stay in sync.
 *
 * Also seeds `useUserStore` from `initDataUnsafe.user` so the Profile page
 * has nick/avatar/language available before the backend confirms.
 */
export function useTelegramBootstrap(): void {
  const setTheme = useThemeStore((s) => s.setTheme);
  const setUser = useUserStore((s) => s.setUser);

  useEffect(() => {
    const { scheme, themeParams } = initTelegramWebApp();
    setTheme(scheme, themeParams);

    try {
      const tgUser = (WebApp.initDataUnsafe?.user ?? null) as TelegramInitUser | null;
      if (tgUser) {
        setUser(userFromTelegram(tgUser));
      }
    } catch {
      /* outside of Telegram: ignore */
    }

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
  }, [setTheme, setUser]);
}
