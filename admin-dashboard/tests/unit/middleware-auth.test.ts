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

async function signAccessToken(role = "support_admin"): Promise<string> {
  return await new SignJWT({ sub: "42", role, type: "access" })
    .setProtectedHeader({ alg: "HS256" })
    .setIssuedAt()
    .setExpirationTime("1h")
    .sign(new TextEncoder().encode("test-secret-please-rotate"));
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

  it("does not expose admin identity claims as response headers", async () => {
    vi.stubEnv("ADMIN_JWT_SECRET", "test-secret-please-rotate");
    vi.stubEnv("ADMIN_JWT_ALGORITHM", "HS256");

    const token = await signAccessToken();
    const request = new NextRequest("https://admin.example/users", {
      headers: {
        cookie: `admin_access_token=${token}`,
      },
    });

    const response = await middleware(request);

    expect(response.status).toBe(200);
    expect(response.headers.get("x-admin-role")).toBeNull();
    expect(response.headers.get("x-admin-sub")).toBeNull();
  });

  it("redirects analysts away from the system area", async () => {
    vi.stubEnv("ADMIN_JWT_SECRET", "test-secret-please-rotate");
    vi.stubEnv("ADMIN_JWT_ALGORITHM", "HS256");

    const token = await signAccessToken("analyst");
    const request = new NextRequest("https://admin.example/system", {
      headers: {
        cookie: `admin_access_token=${token}`,
      },
    });

    const response = await middleware(request);

    expect(response.status).toBe(307);
    expect(response.headers.get("location")).toBe(
      "https://admin.example/dashboard?reason=forbidden",
    );
  });

  it("allows support admins into content but not system", async () => {
    vi.stubEnv("ADMIN_JWT_SECRET", "test-secret-please-rotate");
    vi.stubEnv("ADMIN_JWT_ALGORITHM", "HS256");

    const token = await signAccessToken("support_admin");
    const contentRequest = new NextRequest("https://admin.example/content", {
      headers: {
        cookie: `admin_access_token=${token}`,
      },
    });
    const systemRequest = new NextRequest("https://admin.example/system/rate-limits", {
      headers: {
        cookie: `admin_access_token=${token}`,
      },
    });

    const contentResponse = await middleware(contentRequest);
    const systemResponse = await middleware(systemRequest);

    expect(contentResponse.status).toBe(200);
    expect(systemResponse.status).toBe(307);
    expect(systemResponse.headers.get("location")).toBe(
      "https://admin.example/dashboard?reason=forbidden",
    );
  });
});
