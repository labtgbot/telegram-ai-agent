import type { Page, Route } from "@playwright/test";

export interface TelegramMockUser {
  id: number;
  first_name: string;
  last_name?: string;
  username?: string;
  language_code?: string;
  is_premium?: boolean;
  photo_url?: string;
}

export interface TelegramMockOptions {
  /**
   * Optional pre-formed initData query string. When supplied, it is used as
   * the verbatim `tgWebAppData` value; the SDK exposes it on `WebApp.initData`.
   * When omitted, a deterministic query string is built from `user`/`authDate`/`hash`.
   */
  initData?: string;
  user?: TelegramMockUser;
  authDate?: number;
  hash?: string;
  colorScheme?: "light" | "dark";
  themeParams?: Record<string, string>;
  version?: string;
  platform?: string;
}

const DEFAULT_USER: TelegramMockUser = {
  id: 4242,
  first_name: "Ada",
  last_name: "Lovelace",
  username: "ada",
  language_code: "en",
  is_premium: false,
};

const LIGHT_THEME: Record<string, string> = {
  bg_color: "#ffffff",
  text_color: "#0f172a",
  hint_color: "#64748b",
  link_color: "#2481cc",
  button_color: "#2481cc",
  button_text_color: "#ffffff",
  secondary_bg_color: "#f1f5f9",
};

const DARK_THEME: Record<string, string> = {
  bg_color: "#0f172a",
  text_color: "#f8fafc",
  hint_color: "#94a3b8",
  link_color: "#60a5fa",
  button_color: "#3b82f6",
  button_text_color: "#ffffff",
  secondary_bg_color: "#1e293b",
};

/**
 * Seed the Telegram Mini App SDK (@twa-dev/sdk) by populating `location.hash`
 * with the parameters Telegram normally injects. The SDK reads the hash on
 * import, so the mocked initData/theme/platform become observable through
 * `window.Telegram.WebApp` without overwriting it.
 *
 * Returns the resolved `initData` string (the value `WebApp.initData` will
 * have) so tests can assert it against captured request headers.
 */
export async function installTelegramMock(
  page: Page,
  options: TelegramMockOptions = {},
): Promise<{ initData: string; user: TelegramMockUser }> {
  const user = options.user ?? DEFAULT_USER;
  const authDate = options.authDate ?? Math.floor(Date.now() / 1000);
  const hash = options.hash ?? "mockhash";
  const innerQuery =
    options.initData ??
    [
      `user=${encodeURIComponent(JSON.stringify(user))}`,
      `auth_date=${authDate}`,
      `hash=${hash}`,
    ].join("&");

  const themeParams =
    options.themeParams ??
    (options.colorScheme === "dark" ? DARK_THEME : LIGHT_THEME);
  const version = options.version ?? "7.10";
  const platform = options.platform ?? "tdesktop";

  const hashParts = [
    `tgWebAppData=${encodeURIComponent(innerQuery)}`,
    `tgWebAppVersion=${encodeURIComponent(version)}`,
    `tgWebAppPlatform=${encodeURIComponent(platform)}`,
    `tgWebAppThemeParams=${encodeURIComponent(JSON.stringify(themeParams))}`,
  ];
  const locationHashValue = `#${hashParts.join("&")}`;

  await page.addInitScript((hashValue: string) => {
    try {
      if (window.location.hash !== hashValue) {
        const next =
          window.location.pathname + window.location.search + hashValue;
        window.history.replaceState(null, "", next);
      }
    } catch {
      // ignore — the SDK will fall back to defaults if the hash isn't readable
    }
  }, locationHashValue);

  return { initData: innerQuery, user };
}

/**
 * Register a mock JSON response for an `/api/v1/...` route. Matches the full
 * URL containing `path` so query strings don't break matching.
 */
export async function mockApi(
  page: Page,
  path: string,
  body: unknown,
  options: { status?: number; method?: string } = {},
): Promise<void> {
  const { status = 200, method } = options;
  await page.route(
    (url) => url.pathname.includes(path),
    async (route: Route) => {
      if (method && route.request().method() !== method) {
        await route.fallback();
        return;
      }
      await route.fulfill({
        status,
        contentType: "application/json",
        body: JSON.stringify(body),
      });
    },
  );
}
