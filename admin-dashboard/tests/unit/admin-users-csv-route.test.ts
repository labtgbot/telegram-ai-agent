import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { GET } from "@/app/api/admin/users/export.csv/route";

vi.mock("@/lib/auth/cookies", () => ({
  readAccessToken: vi.fn(),
}));

vi.mock("@/lib/env", () => ({
  serverEnv: () => ({ apiBaseUrl: "http://backend/api/v1" }),
  publicEnv: { apiBaseUrl: "http://backend/api/v1" },
}));

import { readAccessToken } from "@/lib/auth/cookies";

describe("GET /api/admin/users/export.csv", () => {
  beforeEach(() => {
    vi.mocked(readAccessToken).mockResolvedValue("token-xyz");
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("returns 401 when no access token is present", async () => {
    vi.mocked(readAccessToken).mockResolvedValue(undefined);
    const response = await GET(new Request("http://localhost/api/admin/users/export.csv"));
    expect(response.status).toBe(401);
  });

  it("proxies the request and forwards query parameters", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response("id,telegram_id\n1,42\n", {
        status: 200,
        headers: { "Content-Type": "text/csv; charset=utf-8" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const response = await GET(
      new Request("http://localhost/api/admin/users/export.csv?is_banned=true&search=alice"),
    );

    expect(response.status).toBe(200);
    expect(response.headers.get("content-disposition")).toMatch(/attachment; filename="users-/);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [calledUrl, init] = fetchMock.mock.calls[0]!;
    expect(calledUrl).toBe(
      "http://backend/api/v1/admin/users/export.csv?is_banned=true&search=alice",
    );
    expect((init as RequestInit).headers).toEqual({ Authorization: "Bearer token-xyz" });
    expect(await response.text()).toContain("id,telegram_id");
  });

  it("bubbles non-200 upstream responses without download headers", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response("forbidden", {
        status: 403,
        headers: { "Content-Type": "text/plain" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const response = await GET(new Request("http://localhost/api/admin/users/export.csv"));
    expect(response.status).toBe(403);
    expect(response.headers.get("content-disposition")).toBeNull();
  });
});
