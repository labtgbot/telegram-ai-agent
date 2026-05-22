import { expect, test } from "@playwright/test";

test.describe("auth guard", () => {
  test("redirects unauthenticated users to /login", async ({ page }) => {
    await page.goto("/dashboard");
    await expect(page).toHaveURL(/\/login(\?|$)/);
    await expect(page.getByRole("heading", { name: /admin sign-in/i })).toBeVisible();
  });

  test("login form renders Telegram ID input first, then the code step", async ({ page }) => {
    await page.goto("/login");
    await expect(page.getByLabel(/telegram id/i)).toBeVisible();
    await expect(page.getByRole("button", { name: /send code/i })).toBeVisible();
  });
});
