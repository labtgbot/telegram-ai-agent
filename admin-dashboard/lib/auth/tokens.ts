import { jwtVerify, type JWTPayload } from "jose";

import { serverEnv } from "@/lib/env";
import { isAdminRole, type Role } from "@/lib/auth/roles";

export interface AdminJwtPayload extends JWTPayload {
  sub: string;
  role: Role;
  type: "access" | "refresh";
  jti?: string;
}

export class TokenInvalidError extends Error {
  constructor(message = "invalid_token") {
    super(message);
    this.name = "TokenInvalidError";
  }
}

export class TokenExpiredError extends Error {
  constructor(message = "token_expired") {
    super(message);
    this.name = "TokenExpiredError";
  }
}

const ACCESS_COOKIE = "admin_access_token";
const REFRESH_COOKIE = "admin_refresh_token";

export const COOKIE_NAMES = {
  access: ACCESS_COOKIE,
  refresh: REFRESH_COOKIE,
} as const;

function secretKey(): Uint8Array {
  return new TextEncoder().encode(serverEnv().jwtSecret);
}

export async function verifyAdminAccessToken(token: string): Promise<AdminJwtPayload> {
  try {
    const { payload } = await jwtVerify(token, secretKey(), {
      algorithms: [serverEnv().jwtAlgorithm],
    });
    if (payload.type !== "access") {
      throw new TokenInvalidError("not_access_token");
    }
    if (typeof payload.sub !== "string" || !isAdminRole(payload.role as string)) {
      throw new TokenInvalidError("missing_claims");
    }
    return payload as AdminJwtPayload;
  } catch (err) {
    if (err instanceof TokenInvalidError) throw err;
    const code = (err as { code?: string }).code;
    if (code === "ERR_JWT_EXPIRED") {
      throw new TokenExpiredError();
    }
    throw new TokenInvalidError();
  }
}
