// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";

import { serverEnv } from "@/lib/env";

afterEach(() => {
  vi.unstubAllEnvs();
});

describe("serverEnv", () => {
  it("throws in production when ADMIN_JWT_SECRET is missing", () => {
    vi.stubEnv("NODE_ENV", "production");
    vi.stubEnv("ADMIN_JWT_SECRET", undefined);

    expect(() => serverEnv()).toThrow(/ADMIN_JWT_SECRET/);
  });

  it("throws in production when ADMIN_JWT_SECRET is the placeholder", () => {
    vi.stubEnv("NODE_ENV", "production");
    vi.stubEnv("ADMIN_JWT_SECRET", "change-me");

    expect(() => serverEnv()).toThrow(/ADMIN_JWT_SECRET/);
  });
});
