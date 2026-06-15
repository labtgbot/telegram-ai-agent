import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { GET } from "@/app/api/admin/analytics/export.csv/route";

vi.mock("@/lib/auth/cookies", () => ({
  readAccessToken: vi.fn(),
}));

vi.mock("@/lib/auth/tokens", () => ({
  TokenExpiredError: class TokenExpiredError extends Error {},
  TokenInvalidError: class TokenInvalidError extends Error {},
  verifyAdminAccessToken: vi.fn(),
}));

vi.mock("@/lib/env", () => ({
  serverEnv: () => ({ apiBaseUrl: "http://backend/api/v1" }),
  publicEnv: { apiBaseUrl: "http://backend/api/v1" },
}));

import { readAccessToken } from "@/lib/auth/cookies";
import { verifyAdminAccessToken } from "@/lib/auth/tokens";

describe("GET /api/admin/analytics/export.csv", () => {
  beforeEach(() => {
    vi.mocked(readAccessToken).mockResolvedValue("token-xyz");
    vi.mocked(verifyAdminAccessToken).mockResolvedValue({
      sub: "42",
      role: "support_admin",
      type: "access",
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("returns 401 when no access token is present", async () => {
    vi.mocked(readAccessToken).mockResolvedValue(undefined);
    const response = await GET(new Request("http://localhost/api/admin/analytics/export.csv"));
    expect(response.status).toBe(401);
    expect(verifyAdminAccessToken).not.toHaveBeenCalled();
  });

  it("returns 403 for analysts before contacting the backend", async () => {
    vi.mocked(verifyAdminAccessToken).mockResolvedValue({
      sub: "42",
      role: "analyst",
      type: "access",
    });
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const response = await GET(new Request("http://localhost/api/admin/analytics/export.csv"));

    expect(response.status).toBe(403);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("proxies the request, forwards every query param and preserves the upstream filename", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response("bucket,purchases,stars,usd,tokens_sold\n2026-05-01,5,500,6.50,25000\n", {
        status: 200,
        headers: {
          "Content-Type": "text/csv; charset=utf-8",
          "Content-Disposition": 'attachment; filename="revenue-2026-05-01-2026-05-15-day.csv"',
        },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const response = await GET(
      new Request(
        "http://localhost/api/admin/analytics/export.csv?start_date=2026-05-01&end_date=2026-05-15&group_by=day",
      ),
    );

    expect(response.status).toBe(200);
    expect(response.headers.get("content-type")).toBe("text/csv; charset=utf-8");
    expect(response.headers.get("content-disposition")).toBe(
      'attachment; filename="revenue-2026-05-01-2026-05-15-day.csv"',
    );
    expect(response.headers.get("cache-control")).toBe("no-store");
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [calledUrl, init] = fetchMock.mock.calls[0]!;
    expect(calledUrl).toBe(
      "http://backend/api/v1/admin/analytics/export.csv?start_date=2026-05-01&end_date=2026-05-15&group_by=day",
    );
    expect((init as RequestInit).headers).toEqual({ Authorization: "Bearer token-xyz" });
    expect(await response.text()).toContain("2026-05-01,5,500");
  });

  it("falls back to a dated filename if the backend omits Content-Disposition", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response("a,b\n1,2\n", {
          status: 200,
          headers: { "Content-Type": "text/csv; charset=utf-8" },
        }),
      ),
    );

    const response = await GET(new Request("http://localhost/api/admin/analytics/export.csv"));
    expect(response.status).toBe(200);
    expect(response.headers.get("content-disposition")).toMatch(/attachment; filename="revenue-/);
  });

  it("bubbles non-200 upstream responses without download headers", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: { code: "invalid_range", message: "bad range" } }), {
          status: 400,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );

    const response = await GET(
      new Request(
        "http://localhost/api/admin/analytics/export.csv?start_date=2026-12-31&end_date=2025-01-01",
      ),
    );
    expect(response.status).toBe(400);
    expect(response.headers.get("content-disposition")).toBeNull();
    expect(await response.text()).toContain("invalid_range");
  });
});
