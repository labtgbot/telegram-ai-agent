/**
 * Subset of `WebApp.themeParams` we care about.
 *
 * Telegram may add or remove fields over time; treat all values as optional
 * and provide sensible fallbacks when applying them as CSS variables.
 *
 * @see https://core.telegram.org/bots/webapps#themeparams
 */
export interface TelegramThemeParams {
  bg_color?: string;
  secondary_bg_color?: string;
  text_color?: string;
  hint_color?: string;
  link_color?: string;
  button_color?: string;
  button_text_color?: string;
  header_bg_color?: string;
  accent_text_color?: string;
  destructive_text_color?: string;
  section_bg_color?: string;
  section_header_text_color?: string;
  section_separator_color?: string;
  subtitle_text_color?: string;
}

export type TelegramColorScheme = "light" | "dark";

/**
 * Subset of `WebApp.initDataUnsafe.user` we read on bootstrap.
 *
 * @see https://core.telegram.org/bots/webapps#webappuser
 */
export interface TelegramInitUser {
  id: number;
  is_bot?: boolean;
  first_name?: string;
  last_name?: string;
  username?: string;
  language_code?: string;
  is_premium?: boolean;
  photo_url?: string;
}
