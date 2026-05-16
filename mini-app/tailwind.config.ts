import type { Config } from "tailwindcss";

/**
 * Telegram theme params map to CSS variables in `src/index.css`.
 * Tailwind reads those variables so components can use semantic classes
 * (e.g. `bg-tg-bg`, `text-tg-text`) that stay in sync with the active
 * Telegram theme (light / dark / custom).
 *
 * See: https://core.telegram.org/bots/webapps#themeparams
 */
const config: Config = {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: ["class"],
  theme: {
    extend: {
      colors: {
        tg: {
          bg: "var(--tg-color-bg)",
          "secondary-bg": "var(--tg-color-secondary-bg)",
          text: "var(--tg-color-text)",
          hint: "var(--tg-color-hint)",
          link: "var(--tg-color-link)",
          button: "var(--tg-color-button)",
          "button-text": "var(--tg-color-button-text)",
          header: "var(--tg-color-header-bg)",
          accent: "var(--tg-color-accent-text)",
          destructive: "var(--tg-color-destructive-text)",
          "section-bg": "var(--tg-color-section-bg)",
          "section-header": "var(--tg-color-section-header-text)",
          separator: "var(--tg-color-section-separator)",
          subtitle: "var(--tg-color-subtitle-text)",
        },
      },
      borderRadius: {
        tg: "var(--tg-radius)",
      },
      fontFamily: {
        sans: [
          "-apple-system",
          "BlinkMacSystemFont",
          "Segoe UI",
          "Roboto",
          "Helvetica",
          "Arial",
          "sans-serif",
        ],
      },
      boxShadow: {
        tg: "0 2px 8px rgba(0, 0, 0, 0.08)",
      },
    },
  },
  plugins: [],
};

export default config;
