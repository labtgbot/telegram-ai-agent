import { expect, test } from "@playwright/test";

import { installTelegramMock, mockApi } from "./helpers/telegram-mock";

test.describe("daily bonus claim flow", () => {
  test("claims the bonus and updates the balance", async ({ page }) => {
    await installTelegramMock(page);

    let claimed = false;
    await page.route(
      (url) => url.pathname.includes("/user/daily-bonus"),
      async (route) => {
        const method = route.request().method();
        if (method === "GET") {
          await route.fulfill({
            status: 200,
            contentType: "application/json",
            body: JSON.stringify({
              available: !claimed,
              enabled: true,
              streak_day: claimed ? 1 : 0,
              next_amount: claimed ? 12 : 10,
              last_claim_date: claimed ? "2026-05-16" : null,
              next_available_at: "2026-05-17T00:00:00+00:00",
              amounts: [10, 12, 15, 20],
            }),
          });
          return;
        }
        if (method === "POST") {
          claimed = true;
          await route.fulfill({
            status: 200,
            contentType: "application/json",
            body: JSON.stringify({
              amount: 10,
              streak_day: 1,
              new_balance: 260,
              transaction_id: 4242,
              claim_date: "2026-05-16",
              next_available_at: "2026-05-17T00:00:00+00:00",
            }),
          });
          return;
        }
        await route.fallback();
      },
    );

    await page.goto("/home");

    const claim = page.getByTestId("daily-bonus-claim");
    await expect(claim).toBeVisible();
    await expect(claim).toContainText("Claim 10 tokens");
    await claim.click();

    await expect(page.getByTestId("daily-bonus-claimed")).toContainText("+10 tokens");
    await expect(page.getByTestId("daily-bonus-cooldown")).toContainText("00:00 UTC");

    await page.getByRole("link", { name: "Balance" }).click();
    await expect(page.getByTestId("balance")).toHaveText("260");
  });

  test("shows the cooldown state when status reports not-available", async ({ page }) => {
    await installTelegramMock(page);
    await mockApi(page, "/user/daily-bonus", {
      available: false,
      enabled: true,
      streak_day: 3,
      next_amount: 20,
      last_claim_date: "2026-05-15",
      next_available_at: "2026-05-17T00:00:00+00:00",
      amounts: [10, 12, 15, 20],
    });

    await page.goto("/home");
    await expect(page.getByTestId("daily-bonus-cooldown")).toBeVisible();
    await expect(page.getByTestId("daily-bonus-claim")).toHaveCount(0);
  });

  test("renders the disabled state when the loop is paused", async ({ page }) => {
    await installTelegramMock(page);
    await mockApi(page, "/user/daily-bonus", {
      available: false,
      enabled: false,
      streak_day: 0,
      next_amount: 10,
      last_claim_date: null,
      next_available_at: "2026-05-17T00:00:00+00:00",
      amounts: [10, 12, 15, 20],
    });

    await page.goto("/home");
    await expect(page.getByTestId("daily-bonus-disabled")).toBeVisible();
  });
});
