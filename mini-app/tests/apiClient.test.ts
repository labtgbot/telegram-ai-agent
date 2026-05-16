import { describe, expect, it, vi } from "vitest";

import { ApiClient, ApiError } from "@/services/apiClient";

function jsonResponse(body: unknown, init: ResponseInit = {}): Response {
  return new Response(JSON.stringify(body), {
    ...init,
    headers: { "content-type": "application/json", ...(init.headers ?? {}) },
  });
}

describe("ApiClient", () => {
  it("attaches X-Telegram-Init-Data and Accept headers", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse({ ok: true }));
    const client = new ApiClient({
      baseUrl: "https://api.example.com/v1",
      getInitData: () => "tg-init-payload",
      fetchImpl,
    });

    await client.get("/users/me");

    expect(fetchImpl).toHaveBeenCalledTimes(1);
    const [url, init] = fetchImpl.mock.calls[0]!;
    expect(url).toBe("https://api.example.com/v1/users/me");
    const headers = new Headers(init!.headers);
    expect(headers.get("X-Telegram-Init-Data")).toBe("tg-init-payload");
    expect(headers.get("Accept")).toBe("application/json");
    expect(init!.method).toBe("GET");
    expect(init!.body).toBeUndefined();
  });

  it("does not set init data header when not available", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse({ ok: true }));
    const client = new ApiClient({
      baseUrl: "https://api.example.com",
      getInitData: () => "",
      fetchImpl,
    });

    await client.get("/ping");

    const [, init] = fetchImpl.mock.calls[0]!;
    const headers = new Headers(init!.headers);
    expect(headers.has("X-Telegram-Init-Data")).toBe(false);
  });

  it("serialises JSON bodies and sets content-type", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse({ id: 1 }));
    const client = new ApiClient({
      baseUrl: "https://api.example.com",
      getInitData: () => "tg",
      fetchImpl,
    });

    await client.post("/items", { name: "token-pack" });

    const [, init] = fetchImpl.mock.calls[0]!;
    expect(init!.method).toBe("POST");
    expect(init!.body).toBe(JSON.stringify({ name: "token-pack" }));
    const headers = new Headers(init!.headers);
    expect(headers.get("Content-Type")).toBe("application/json");
  });

  it("appends query parameters", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse([]));
    const client = new ApiClient({
      baseUrl: "https://api.example.com",
      getInitData: () => "",
      fetchImpl,
    });

    await client.get("/list", { query: { limit: 10, q: "tokens", empty: null } });

    const [url] = fetchImpl.mock.calls[0]!;
    expect(url).toBe("https://api.example.com/list?limit=10&q=tokens");
  });

  it("throws ApiError with parsed body on non-2xx", async () => {
    const fetchImpl = vi
      .fn()
      .mockImplementation(() => Promise.resolve(jsonResponse({ detail: "boom" }, { status: 422 })));
    const client = new ApiClient({
      baseUrl: "https://api.example.com",
      getInitData: () => "",
      fetchImpl,
    });

    await expect(client.get("/fail")).rejects.toBeInstanceOf(ApiError);

    let captured: ApiError | undefined;
    try {
      await client.get("/fail");
    } catch (err) {
      captured = err as ApiError;
    }
    expect(captured).toBeInstanceOf(ApiError);
    expect(captured?.status).toBe(422);
    expect(captured?.message).toBe("boom");
    expect(captured?.body).toEqual({ detail: "boom" });
  });
});
