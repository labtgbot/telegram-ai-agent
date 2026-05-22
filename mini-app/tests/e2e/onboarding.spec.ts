import { expect, test } from "@playwright/test";

import { installTelegramMock, mockApi } from "./helpers/telegram-mock";

test.describe("onboarding via Telegram WebApp mock", () => {
  test("seeds the user from initDataUnsafe and greets them on the home page", async ({ page }) => {
    const telegram = await installTelegramMock(page, {
      user: {
        id: 100200,
        first_name: "Ada",
        last_name: "Lovelace",
        username: "ada",
        language_code: "en",
      },
    });
    await mockApi(page, "/user/daily-bonus", {
      available: true,
      enabled: true,
      streak_day: 0,
      next_amount: 10,
      last_claim_date: null,
      next_available_at: "2026-05-17T00:00:00+00:00",
      amounts: [10, 12, 15, 20],
    });
    await mockApi(page, "/users/me", {
      id: 1,
      telegram_id: 100200,
      username: "ada",
      first_name: "Ada",
      last_name: "Lovelace",
      language_code: "en",
      role: "user",
      referral_code: "ADA-CODE",
      is_premium: false,
      is_banned: false,
      photo_url: null,
      premium_expires_at: null,
      created_at: "2025-01-01T00:00:00+00:00",
      totp_enabled: false,
    });

    await telegram.goto();

    await expect(page.getByTestId("active-scheme")).toHaveText(/light|dark/);
    await expect(page.getByText(/Hi Ada/)).toBeVisible();
    await expect(page.getByTestId("daily-bonus-claim")).toBeVisible();
  });

  test("hydrates the profile page from the Telegram identity", async ({ page }) => {
    const telegram = await installTelegramMock(page, {
      user: {
        id: 100201,
        first_name: "Grace",
        last_name: "Hopper",
        username: "grace",
        language_code: "en",
      },
    });
    await mockApi(
      page,
      "/users/me",
      {
        id: 1,
        telegram_id: 100201,
        username: "grace",
        first_name: "Grace",
        last_name: "Hopper",
        language_code: "en",
        role: "user",
        referral_code: "GRACE-CODE",
        is_premium: false,
        is_banned: false,
        photo_url: null,
        premium_expires_at: null,
        created_at: "2025-01-01T00:00:00+00:00",
        totp_enabled: false,
      },
      { method: "GET" },
    );

    await telegram.goto("/profile");

    await expect(page.getByTestId("profile-name")).toHaveText("Grace Hopper");
    await expect(page.getByTestId("profile-username")).toHaveText("@grace");
    await expect(page.getByTestId("row-referral")).toContainText("GRACE-CODE");
  });

  test("falls back to the empty profile state when no Telegram user is present", async ({
    page,
  }) => {
    await page.addInitScript(() => {
      (window as unknown as { Telegram: { WebApp: unknown } }).Telegram = {
        WebApp: {
          initData: "",
          initDataUnsafe: {},
          colorScheme: "light",
          themeParams: {},
          ready: () => undefined,
          expand: () => undefined,
          onEvent: () => undefined,
          offEvent: () => undefined,
        },
      };
    });
    await mockApi(
      page,
      "/users/me",
      { detail: "Not found" },
      { method: "GET", status: 404 },
    );

    await page.goto("/profile");
    await expect(page.getByTestId("profile-empty")).toBeVisible();
  });
});
