import { expect, test } from "@playwright/test";

import { installTelegramMock, mockApi } from "./helpers/telegram-mock";

test.describe("settings flow and init-data propagation", () => {
  test("propagates X-Telegram-Init-Data on settings API calls (data-export flow)", async ({
    page,
  }) => {
    const initData = "mock-init-data-xyz";
    const telegram = await installTelegramMock(page, {
      initData,
      user: { id: 42, first_name: "Linus", username: "linus", language_code: "en" },
    });

    let capturedInitData: string | null = null;
    await page.route(
      (url) => url.pathname.includes("/user/me/export"),
      async (route) => {
        expect(route.request().method()).toBe("GET");
        capturedInitData = route.request().headers()["x-telegram-init-data"] ?? null;
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            schema_version: "1.0",
            generated_at: "2026-06-07T00:00:00+00:00",
            user: { id: 42 },
            transactions: [],
            subscriptions: [],
            chat_threads: [],
            chat_messages: [],
            daily_bonus_claims: [],
            referrals_summary: { count: 0 },
            notes: [],
          }),
        });
      },
    );

    await telegram.goto("/settings");

    await page.getByLabel("Email").fill("linus@example.com");
    await page.getByRole("button", { name: "Request export" }).click();

    await expect(page.getByText(/Export requested/)).toBeVisible();
    expect(capturedInitData).toBe(initData);
  });

  test("reflects the Telegram color scheme in the header", async ({ page }) => {
    const telegram = await installTelegramMock(page, { colorScheme: "dark" });
    await mockApi(page, "/user/daily-bonus", {
      available: false,
      enabled: false,
      streak_day: 0,
      next_amount: 0,
      last_claim_date: null,
      next_available_at: "2026-05-17T00:00:00+00:00",
      amounts: [],
    });
    await telegram.goto();
    await expect(page.getByTestId("active-scheme")).toHaveText("dark");
  });
});
