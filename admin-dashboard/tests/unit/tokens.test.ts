// @vitest-environment node
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { SignJWT } from "jose";

import { TokenExpiredError, TokenInvalidError, verifyAdminAccessToken } from "@/lib/auth/tokens";

const SECRET = "test-secret-please-rotate";

beforeAll(() => {
  process.env.ADMIN_JWT_SECRET = SECRET;
  process.env.ADMIN_JWT_ALGORITHM = "HS256";
});

afterAll(() => {
  delete process.env.ADMIN_JWT_SECRET;
  delete process.env.ADMIN_JWT_ALGORITHM;
});

async function sign(payload: Record<string, unknown>, expIn = "1h"): Promise<string> {
  return await new SignJWT(payload)
    .setProtectedHeader({ alg: "HS256" })
    .setIssuedAt()
    .setExpirationTime(expIn)
    .sign(new TextEncoder().encode(SECRET));
}

describe("verifyAdminAccessToken", () => {
  it("returns the payload for a valid access token", async () => {
    const token = await sign({ sub: "42", role: "support_admin", type: "access" });
    const payload = await verifyAdminAccessToken(token);
    expect(payload.sub).toBe("42");
    expect(payload.role).toBe("support_admin");
  });

  it("rejects refresh tokens used as access tokens", async () => {
    const token = await sign({ sub: "1", role: "super_admin", type: "refresh" });
    await expect(verifyAdminAccessToken(token)).rejects.toBeInstanceOf(TokenInvalidError);
  });

  it("rejects tokens missing the role claim", async () => {
    const token = await sign({ sub: "1", type: "access" });
    await expect(verifyAdminAccessToken(token)).rejects.toBeInstanceOf(TokenInvalidError);
  });

  it("rejects tokens signed with the wrong secret", async () => {
    const token = await new SignJWT({ sub: "1", role: "analyst", type: "access" })
      .setProtectedHeader({ alg: "HS256" })
      .setIssuedAt()
      .setExpirationTime("1h")
      .sign(new TextEncoder().encode("not-the-secret"));
    await expect(verifyAdminAccessToken(token)).rejects.toBeInstanceOf(TokenInvalidError);
  });

  it("raises TokenExpiredError for expired tokens", async () => {
    const token = await new SignJWT({ sub: "1", role: "analyst", type: "access" })
      .setProtectedHeader({ alg: "HS256" })
      .setIssuedAt(Math.floor(Date.now() / 1000) - 120)
      .setExpirationTime(Math.floor(Date.now() / 1000) - 60)
      .sign(new TextEncoder().encode(SECRET));
    await expect(verifyAdminAccessToken(token)).rejects.toBeInstanceOf(TokenExpiredError);
  });
});
