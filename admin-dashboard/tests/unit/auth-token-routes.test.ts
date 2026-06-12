// @vitest-environment node
import { beforeEach, describe, expect, it, vi } from "vitest";

const persistTokens = vi.fn();
const clearTokens = vi.fn();
const readRefreshToken = vi.fn();

vi.mock("@/lib/auth/cookies", () => ({
  persistTokens,
  clearTokens,
  readRefreshToken,
}));

describe("admin auth token route handlers", () => {
  beforeEach(() => {
    vi.stubEnv("API_BASE_URL", "https://backend.example/api/v1");
    vi.stubEnv("ADMIN_JWT_SECRET", "test-secret-please-rotate");
    vi.stubEnv("ADMIN_JWT_ALGORITHM", "HS256");
    vi.stubGlobal("fetch", vi.fn());
    persistTokens.mockReset();
    clearTokens.mockReset();
    readRefreshToken.mockReset();
  });

  it("rejects malformed login verify payloads without setting cookies", async () => {
    const { POST } = await import("@/app/api/auth/login/verify/route");
    vi.mocked(fetch).mockResolvedValue(
      new Response(JSON.stringify({ access_token: "", expires_in: 0 }), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );

    const response = await POST(
      new Request("https://admin.example/api/auth/login/verify", {
        method: "POST",
        body: JSON.stringify({ telegram_id: 42, code: "123456" }),
      }),
    );

    expect(response.status).toBe(502);
    expect(await response.json()).toMatchObject({ code: "bad_upstream_token_payload" });
    expect(persistTokens).not.toHaveBeenCalled();
  });

  it("persists validated login verify tokens", async () => {
    const { POST } = await import("@/app/api/auth/login/verify/route");
    vi.mocked(fetch).mockResolvedValue(
      new Response(
        JSON.stringify({
          access_token: "access-token",
          refresh_token: "refresh-token",
          expires_in: 900,
        }),
        {
          status: 200,
          headers: { "content-type": "application/json" },
        },
      ),
    );

    const response = await POST(
      new Request("https://admin.example/api/auth/login/verify", {
        method: "POST",
        body: JSON.stringify({ telegram_id: 42, code: "123456" }),
      }),
    );

    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ status: "ok", expires_in: 900 });
    expect(persistTokens).toHaveBeenCalledWith({
      access_token: "access-token",
      refresh_token: "refresh-token",
      expires_in: 900,
    });
  });

  it("rejects malformed refresh payloads without setting cookies", async () => {
    const { POST } = await import("@/app/api/auth/refresh/route");
    readRefreshToken.mockResolvedValue("refresh-token");
    vi.mocked(fetch).mockResolvedValue(
      new Response(JSON.stringify({ access_token: "access-token" }), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );

    const response = await POST();

    expect(response.status).toBe(502);
    expect(await response.json()).toMatchObject({ code: "bad_upstream_token_payload" });
    expect(persistTokens).not.toHaveBeenCalled();
    expect(clearTokens).not.toHaveBeenCalled();
  });

  it("revokes backend refresh session during logout before clearing cookies", async () => {
    const { POST } = await import("@/app/api/auth/logout/route");
    readRefreshToken.mockResolvedValue("refresh-token");
    vi.mocked(fetch).mockResolvedValue(
      new Response(JSON.stringify({ status: "ok" }), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );

    const response = await POST();

    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ status: "ok" });
    expect(fetch).toHaveBeenCalledWith("https://backend.example/api/v1/auth/admin/logout", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: "refresh-token" }),
    });
    expect(clearTokens).toHaveBeenCalled();
  });

  it("clears logout cookies without upstream call when refresh cookie is missing", async () => {
    const { POST } = await import("@/app/api/auth/logout/route");
    readRefreshToken.mockResolvedValue(undefined);

    const response = await POST();

    expect(response.status).toBe(200);
    expect(fetch).not.toHaveBeenCalled();
    expect(clearTokens).toHaveBeenCalled();
  });
});
