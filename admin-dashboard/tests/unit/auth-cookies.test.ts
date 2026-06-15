import { beforeEach, describe, expect, it, vi } from "vitest";

const cookieStore = vi.hoisted(() => ({
  cookies: vi.fn(),
  delete: vi.fn(),
  get: vi.fn(),
  set: vi.fn(),
}));

vi.mock("next/headers", () => ({
  cookies: cookieStore.cookies,
}));

import { CSRF_COOKIE_NAME } from "@/lib/auth/csrf";
import { clearTokens, persistTokens, readCsrfToken } from "@/lib/auth/cookies";
import { COOKIE_NAMES } from "@/lib/auth/tokens";

describe("admin auth cookies", () => {
  beforeEach(() => {
    cookieStore.cookies.mockResolvedValue({
      delete: cookieStore.delete,
      get: cookieStore.get,
      set: cookieStore.set,
    });
    cookieStore.delete.mockReset();
    cookieStore.get.mockReset();
    cookieStore.set.mockReset();
  });

  it("persists a readable CSRF cookie alongside HttpOnly token cookies", async () => {
    await persistTokens({
      access_token: "access-token",
      refresh_token: "refresh-token",
      expires_in: 900,
    });

    expect(cookieStore.set).toHaveBeenCalledWith(
      CSRF_COOKIE_NAME,
      expect.stringMatching(/^[A-Za-z0-9_-]+$/),
      expect.objectContaining({
        httpOnly: false,
        maxAge: 14 * 24 * 60 * 60,
        path: "/",
        sameSite: "strict",
      }),
    );
  });

  it("clears the CSRF cookie with the auth token cookies", async () => {
    await clearTokens();

    expect(cookieStore.delete).toHaveBeenCalledWith(COOKIE_NAMES.access);
    expect(cookieStore.delete).toHaveBeenCalledWith(COOKIE_NAMES.refresh);
    expect(cookieStore.delete).toHaveBeenCalledWith(COOKIE_NAMES.csrf);
  });

  it("reads the CSRF cookie value", async () => {
    cookieStore.get.mockReturnValue({ value: "csrf-token" });

    await expect(readCsrfToken()).resolves.toBe("csrf-token");
    expect(cookieStore.get).toHaveBeenCalledWith(COOKIE_NAMES.csrf);
  });
});
