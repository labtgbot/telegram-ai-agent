import { describe, expect, it } from "vitest";

import { resolveLanguage, translate } from "@/i18n";

describe("i18n", () => {
  describe("resolveLanguage", () => {
    it("prefers an explicit user preference", () => {
      expect(resolveLanguage("ru", "en")).toBe("ru");
      expect(resolveLanguage("en", "ru")).toBe("en");
    });

    it("auto picks Russian for ru-style Telegram language codes", () => {
      expect(resolveLanguage("auto", "ru")).toBe("ru");
      expect(resolveLanguage("auto", "ru-RU")).toBe("ru");
      expect(resolveLanguage("auto", "RU")).toBe("ru");
    });

    it("auto falls back to English for unknown or missing language codes", () => {
      expect(resolveLanguage("auto", "fr")).toBe("en");
      expect(resolveLanguage("auto", null)).toBe("en");
      expect(resolveLanguage("auto", undefined)).toBe("en");
    });
  });

  describe("translate", () => {
    it("returns the localised value for a deep key", () => {
      expect(translate("en", "nav.profile")).toBe("Profile");
      expect(translate("ru", "nav.profile")).toBe("Профиль");
    });

    it("substitutes interpolation tokens", () => {
      expect(translate("en", "history.tokens", { count: 42 })).toBe("42 tokens");
      expect(translate("ru", "history.page", { page: 3 })).toBe("Страница 3");
    });

    it("returns the key when the translation is missing", () => {
      expect(translate("en", "nav.missing" as never)).toBe("nav.missing");
    });
  });
});
