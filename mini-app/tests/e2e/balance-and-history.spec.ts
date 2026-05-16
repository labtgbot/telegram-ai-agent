import { expect, test } from "@playwright/test";

import { installTelegramMock, mockApi } from "./helpers/telegram-mock";

test.describe("balance and history pages", () => {
  test("shows the placeholder when the store balance is empty", async ({ page }) => {
    await installTelegramMock(page);
    await page.goto("/balance");
    await expect(page.getByTestId("balance")).toHaveText("—");
    await expect(page.getByText(/Buy more tokens/)).toBeVisible();
  });

  test("renders the usage history page with mocked data", async ({ page }) => {
    await installTelegramMock(page);
    await mockApi(
      page,
      "/user/usage-history",
      {
        items: [
          {
            id: 1,
            service_type: "text",
            tokens_consumed: 24,
            processing_time_ms: 312,
            response_status: "success",
            created_at: "2026-05-15T10:30:00+00:00",
          },
          {
            id: 2,
            service_type: "image",
            tokens_consumed: 96,
            processing_time_ms: 1820,
            response_status: "success",
            created_at: "2026-05-14T08:15:00+00:00",
          },
        ],
        has_more: false,
        page: 1,
        limit: 10,
        total: 2,
      },
      { method: "GET" },
    );

    await page.goto("/history");

    await expect(page.getByTestId("history-list")).toBeVisible();
    const rows = page.getByTestId("history-list").getByRole("listitem");
    await expect(rows).toHaveCount(2);
    await expect(rows.first()).toContainText("Text");
    await expect(rows.first()).toContainText("24 tokens");
  });

  test("falls back to the empty state when there is no history", async ({ page }) => {
    await installTelegramMock(page);
    await mockApi(
      page,
      "/user/usage-history",
      { items: [], has_more: false, page: 1, limit: 10, total: 0 },
      { method: "GET" },
    );

    await page.goto("/history");
    await expect(page.getByTestId("history-empty")).toBeVisible();
  });
});
