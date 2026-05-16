import { create } from "zustand";

import { applyTelegramTheme } from "@/services/telegram";
import type { TelegramColorScheme, TelegramThemeParams } from "@/types/telegram";

interface ThemeState {
  scheme: TelegramColorScheme;
  themeParams: TelegramThemeParams;
  setTheme: (scheme: TelegramColorScheme, themeParams: TelegramThemeParams) => void;
}

export const useThemeStore = create<ThemeState>((set) => ({
  scheme: "light",
  themeParams: {},
  setTheme: (scheme, themeParams) => {
    applyTelegramTheme(themeParams, scheme);
    set({ scheme, themeParams });
  },
}));
