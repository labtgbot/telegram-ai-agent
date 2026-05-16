import { describe, expect, it } from "vitest";

import { applyTelegramTheme } from "@/services/telegram";

describe("applyTelegramTheme", () => {
  it("sets CSS variables and toggles tg-dark class for dark scheme", () => {
    const root = document.documentElement;
    root.classList.remove("tg-dark");

    applyTelegramTheme(
      {
        bg_color: "#101010",
        text_color: "#fefefe",
        button_color: "#5288c1",
      },
      "dark",
    );

    expect(root.classList.contains("tg-dark")).toBe(true);
    expect(root.dataset["tgScheme"]).toBe("dark");
    expect(root.style.getPropertyValue("--tg-color-bg")).toBe("#101010");
    expect(root.style.getPropertyValue("--tg-color-text")).toBe("#fefefe");
    expect(root.style.getPropertyValue("--tg-color-button")).toBe("#5288c1");
  });

  it("removes tg-dark class for light scheme and ignores missing params", () => {
    const root = document.documentElement;
    root.classList.add("tg-dark");

    applyTelegramTheme({ bg_color: "#ffffff" }, "light");

    expect(root.classList.contains("tg-dark")).toBe(false);
    expect(root.dataset["tgScheme"]).toBe("light");
    expect(root.style.getPropertyValue("--tg-color-bg")).toBe("#ffffff");
  });
});
