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

    // New BalancePage reads /user/balance via React Query, so we mock it to
    // reflect the post-claim balance once the bonus has been claimed.
    await page.route(
      (url) => url.pathname.endsWith("/user/balance"),
      async (route) => {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            token_balance: claimed ? 260 : 250,
            is_premium: false,
            premium_expires_at: null,
            daily_bonus_available: !claimed,
          }),
        });
      },
    );
    await mockApi(page, "/payment/packages", { items: [] }, { method: "GET" });
    await mockApi(
      page,
      "/user/referral",
      {
        referral_code: "REF-1",
        referrals_count: 0,
        bonus_tokens_earned: 0,
        referral_link: "https://t.me/test_bot?start=REF-1",
      },
      { method: "GET" },
    );
    await mockApi(
      page,
      "/user/transactions",
      { items: [], total: 0, page: 1, limit: 10, has_more: false },
      { method: "GET" },
    );

    await page.goto("/");

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

    await page.goto("/");
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

    await page.goto("/");
    await expect(page.getByTestId("daily-bonus-disabled")).toBeVisible();
  });
});
