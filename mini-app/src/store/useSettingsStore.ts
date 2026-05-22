import { create } from "zustand";
import { persist, createJSONStorage } from "zustand/middleware";

import type { LanguagePreference } from "@/i18n";

export type AiResponseSize = "short" | "medium" | "long";

export interface SettingsState {
  language: LanguagePreference;
  notificationsEnabled: boolean;
  aiResponseSize: AiResponseSize;
  setLanguage: (language: LanguagePreference) => void;
  setNotificationsEnabled: (enabled: boolean) => void;
  setAiResponseSize: (size: AiResponseSize) => void;
  reset: () => void;
}

const DEFAULTS = {
  language: "auto" as LanguagePreference,
  notificationsEnabled: true,
  aiResponseSize: "medium" as AiResponseSize,
};

export const SETTINGS_STORAGE_KEY = "tg-ai-agent.settings";

export const useSettingsStore = create<SettingsState>()(
  persist(
    (set) => ({
      ...DEFAULTS,
      setLanguage: (language) => set({ language }),
      setNotificationsEnabled: (notificationsEnabled) => set({ notificationsEnabled }),
      setAiResponseSize: (aiResponseSize) => set({ aiResponseSize }),
      reset: () => set({ ...DEFAULTS }),
    }),
    {
      name: SETTINGS_STORAGE_KEY,
      storage: createJSONStorage(() => {
        if (typeof window !== "undefined" && window.localStorage) {
          return window.localStorage;
        }
        return memoryStorage();
      }),
      version: 1,
      partialize: (state) => ({
        language: state.language,
        notificationsEnabled: state.notificationsEnabled,
        aiResponseSize: state.aiResponseSize,
      }),
    },
  ),
);

function memoryStorage(): Storage {
  const map = new Map<string, string>();
  return {
    get length() {
      return map.size;
    },
    clear: () => map.clear(),
    getItem: (key) => map.get(key) ?? null,
    key: (index) => Array.from(map.keys())[index] ?? null,
    removeItem: (key) => {
      map.delete(key);
    },
    setItem: (key, value) => {
      map.set(key, value);
    },
  };
}
