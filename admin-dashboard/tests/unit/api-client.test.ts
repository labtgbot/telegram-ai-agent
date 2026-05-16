import { describe, expect, it, vi } from "vitest";

import { ApiClient } from "@/lib/api/client";
import { ApiError, isApiError } from "@/lib/api/errors";

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("ApiClient", () => {
  it("attaches Authorization header from getAccessToken", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse(200, { ok: true }));
    const client = new ApiClient({
      baseUrl: "https://api.example.com",
      getAccessToken: () => "abc",
      fetchImpl,
    });

    await client.get("/ping");

    expect(fetchImpl).toHaveBeenCalledTimes(1);
    const [, init] = fetchImpl.mock.calls[0]!;
    const headers = init.headers as Headers;
    expect(headers.get("authorization")).toBe("Bearer abc");
  });

  it("normalises FastAPI error responses into ApiError", async () => {
    const fetchImpl = vi
      .fn()
      .mockResolvedValue(jsonResponse(404, { detail: "user_not_found" }));
    const client = new ApiClient({ baseUrl: "https://api.example.com", fetchImpl });

    let captured: unknown;
    try {
      await client.get("/admin/users/42");
    } catch (err) {
      captured = err;
    }
    expect(isApiError(captured)).toBe(true);
    const apiErr = captured as ApiError;
    expect(apiErr.status).toBe(404);
    expect(apiErr.code).toBe("user_not_found");
  });

  it("refreshes the token on 401 and retries once", async () => {
    const fetchImpl = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(401, { detail: "expired" }))
      .mockResolvedValueOnce(jsonResponse(200, { ok: true }));
    const refresh = vi.fn().mockResolvedValue("new-token");
    const onAuthLost = vi.fn();
    const client = new ApiClient({
      baseUrl: "https://api.example.com",
      getAccessToken: () => "old",
      refreshAccessToken: refresh,
      onAuthLost,
      fetchImpl,
    });

    await client.get("/admin/me");

    expect(fetchImpl).toHaveBeenCalledTimes(2);
    expect(refresh).toHaveBeenCalledTimes(1);
    expect(onAuthLost).not.toHaveBeenCalled();
  });

  it("calls onAuthLost when refresh returns no token", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse(401, { detail: "expired" }));
    const refresh = vi.fn().mockResolvedValue(undefined);
    const onAuthLost = vi.fn();
    const client = new ApiClient({
      baseUrl: "https://api.example.com",
      getAccessToken: () => "old",
      refreshAccessToken: refresh,
      onAuthLost,
      fetchImpl,
    });

    await expect(client.get("/admin/me")).rejects.toBeInstanceOf(ApiError);
    expect(onAuthLost).toHaveBeenCalledWith(401);
  });

  it("calls onAuthLost on 403 without retrying", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse(403, { detail: "forbidden" }));
    const refresh = vi.fn();
    const onAuthLost = vi.fn();
    const client = new ApiClient({
      baseUrl: "https://api.example.com",
      getAccessToken: () => "ok",
      refreshAccessToken: refresh,
      onAuthLost,
      fetchImpl,
    });

    await expect(client.get("/admin/pricing")).rejects.toMatchObject({ status: 403 });
    expect(refresh).not.toHaveBeenCalled();
    expect(onAuthLost).toHaveBeenCalledWith(403);
  });

  it("serialises JSON body and sets content-type", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse(200, { ok: true }));
    const client = new ApiClient({ baseUrl: "https://api.example.com", fetchImpl });

    await client.post("/admin/users/7/add-tokens", { tokens: 100, reason: "test" });

    const [, init] = fetchImpl.mock.calls[0]!;
    expect(init.method).toBe("POST");
    expect((init.headers as Headers).get("content-type")).toBe("application/json");
    expect(init.body).toBe(JSON.stringify({ tokens: 100, reason: "test" }));
  });

  it("appends query parameters to GET requests", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse(200, { ok: true }));
    const client = new ApiClient({ baseUrl: "https://api.example.com", fetchImpl });

    await client.get("/admin/users", { query: { page: 2, search: "alice", banned: false } });

    const [url] = fetchImpl.mock.calls[0]!;
    expect(url).toBe("https://api.example.com/admin/users?page=2&search=alice&banned=false");
  });
});
