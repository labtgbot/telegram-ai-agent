import WebApp from "@twa-dev/sdk";

import type { TelegramColorScheme, TelegramThemeParams } from "@/types/telegram";

const THEME_VARS: Array<[keyof TelegramThemeParams, string]> = [
  ["bg_color", "--tg-color-bg"],
  ["secondary_bg_color", "--tg-color-secondary-bg"],
  ["text_color", "--tg-color-text"],
  ["hint_color", "--tg-color-hint"],
  ["link_color", "--tg-color-link"],
  ["button_color", "--tg-color-button"],
  ["button_text_color", "--tg-color-button-text"],
  ["header_bg_color", "--tg-color-header-bg"],
  ["accent_text_color", "--tg-color-accent-text"],
  ["destructive_text_color", "--tg-color-destructive-text"],
  ["section_bg_color", "--tg-color-section-bg"],
  ["section_header_text_color", "--tg-color-section-header-text"],
  ["section_separator_color", "--tg-color-section-separator"],
  ["subtitle_text_color", "--tg-color-subtitle-text"],
];

/** Apply Telegram theme params as CSS variables on `:root`. */
export function applyTelegramTheme(
  params: TelegramThemeParams,
  scheme: TelegramColorScheme,
  doc: Document = document,
): void {
  const root = doc.documentElement;
  for (const [key, cssVar] of THEME_VARS) {
    const value = params[key];
    if (value) {
      root.style.setProperty(cssVar, value);
    }
  }
  root.classList.toggle("tg-dark", scheme === "dark");
  root.dataset.tgScheme = scheme;
}

/**
 * Initialise the Telegram WebApp: notify Telegram we're ready, expand to
 * full height, and sync theme params + colour scheme.
 *
 * Safe to call even when the page is opened outside of Telegram — the SDK
 * stubs the API and `themeParams` is empty, leaving the default theme.
 */
export function initTelegramWebApp(): {
  scheme: TelegramColorScheme;
  themeParams: TelegramThemeParams;
} {
  try {
    WebApp.ready();
    WebApp.expand();
  } catch {
    /* SDK is best-effort outside of Telegram. */
  }

  const scheme: TelegramColorScheme = WebApp.colorScheme === "dark" ? "dark" : "light";
  const themeParams = (WebApp.themeParams ?? {}) as TelegramThemeParams;
  applyTelegramTheme(themeParams, scheme);
  return { scheme, themeParams };
}

/** Returns Telegram WebApp `initData` for backend auth, or empty string. */
export function getInitData(): string {
  try {
    return WebApp.initData ?? "";
  } catch {
    return "";
  }
}

export { WebApp };
