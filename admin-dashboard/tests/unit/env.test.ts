// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";

import { serverEnv } from "@/lib/env";

const PRODUCTION_ADMIN_JWT_SECRET = "x".repeat(32);
const PRODUCTION_API_BASE_URL = "http://backend:8000/api/v1";
const PRODUCTION_PUBLIC_API_BASE_URL = "https://bot.example.com/api/v1";

function stubProductionApiUrls() {
  vi.stubEnv("API_BASE_URL", PRODUCTION_API_BASE_URL);
  vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", PRODUCTION_PUBLIC_API_BASE_URL);
}

afterEach(() => {
  vi.unstubAllEnvs();
});

describe("serverEnv", () => {
  it("throws in production when ADMIN_JWT_SECRET is missing", () => {
    vi.stubEnv("NODE_ENV", "production");
    vi.stubEnv("ADMIN_JWT_SECRET", undefined);
    stubProductionApiUrls();

    expect(() => serverEnv()).toThrow(/ADMIN_JWT_SECRET/);
  });

  it("throws in production when ADMIN_JWT_SECRET is the placeholder", () => {
    vi.stubEnv("NODE_ENV", "production");
    vi.stubEnv("ADMIN_JWT_SECRET", "change-me");
    stubProductionApiUrls();

    expect(() => serverEnv()).toThrow(/ADMIN_JWT_SECRET/);
  });

  it("throws in production when API_BASE_URL falls back to localhost", () => {
    vi.stubEnv("NODE_ENV", "production");
    vi.stubEnv("ADMIN_JWT_SECRET", PRODUCTION_ADMIN_JWT_SECRET);
    vi.stubEnv("API_BASE_URL", undefined);
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", undefined);

    expect(() => serverEnv()).toThrow(/API_BASE_URL/);
  });

  it("allows non-localhost API URLs in production", () => {
    vi.stubEnv("NODE_ENV", "production");
    vi.stubEnv("ADMIN_JWT_SECRET", PRODUCTION_ADMIN_JWT_SECRET);
    stubProductionApiUrls();

    expect(serverEnv().apiBaseUrl).toBe(PRODUCTION_API_BASE_URL);
  });
});
