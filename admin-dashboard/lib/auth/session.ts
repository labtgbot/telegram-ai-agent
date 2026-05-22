import "server-only";

import { readAccessToken } from "@/lib/auth/cookies";
import { verifyAdminAccessToken, TokenExpiredError, TokenInvalidError } from "@/lib/auth/tokens";
import type { Role } from "@/lib/auth/roles";

export interface AdminSession {
  sub: string;
  role: Role;
}

/**
 * Returns the current session derived from the access-token cookie, or
 * undefined if it is missing/expired. Server components call this to render
 * role-aware UI; the middleware enforces redirects before they run.
 */
export async function getAdminSession(): Promise<AdminSession | undefined> {
  const token = await readAccessToken();
  if (!token) return undefined;
  try {
    const payload = await verifyAdminAccessToken(token);
    return { sub: payload.sub, role: payload.role };
  } catch (err) {
    if (err instanceof TokenExpiredError || err instanceof TokenInvalidError) {
      return undefined;
    }
    throw err;
  }
}
