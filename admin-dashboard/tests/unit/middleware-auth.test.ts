// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";
import { SignJWT } from "jose";
import { NextRequest } from "next/server";

import { middleware } from "@/middleware";

afterEach(() => {
  vi.unstubAllEnvs();
});

async function signWithPlaceholder(): Promise<string> {
  return await new SignJWT({ sub: "1", role: "super_admin", type: "access" })
    .setProtectedHeader({ alg: "HS256" })
    .setIssuedAt()
    .setExpirationTime("1h")
    .sign(new TextEncoder().encode("change-me"));
}

describe("middleware admin auth", () => {
  it("rejects a forged production token signed with the placeholder secret", async () => {
    vi.stubEnv("NODE_ENV", "production");
    vi.stubEnv("ADMIN_JWT_SECRET", undefined);
    vi.stubEnv("ADMIN_JWT_ALGORITHM", "HS256");

    const token = await signWithPlaceholder();
    const request = new NextRequest("https://admin.example/dashboard", {
      headers: {
        cookie: `admin_access_token=${token}`,
      },
    });

    const response = await middleware(request);

    expect(response.status).toBe(307);
    expect(response.headers.get("location")).toBe(
      "https://admin.example/login?from=%2Fdashboard&reason=invalid",
    );
  });
});
