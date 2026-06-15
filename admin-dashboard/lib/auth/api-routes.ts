import { NextResponse } from "next/server";

import { readAccessToken } from "@/lib/auth/cookies";
import { roleSatisfies, type Role } from "@/lib/auth/roles";
import { TokenExpiredError, TokenInvalidError, verifyAdminAccessToken } from "@/lib/auth/tokens";

type AdminApiAuthResult = { ok: true; token: string } | { ok: false; response: Response };

export async function requireAdminApiRole(required: Role): Promise<AdminApiAuthResult> {
  const token = await readAccessToken();
  if (!token) {
    return { ok: false, response: NextResponse.json({ detail: "unauthorized" }, { status: 401 }) };
  }

  try {
    const payload = await verifyAdminAccessToken(token);
    if (!roleSatisfies(payload.role, required)) {
      return { ok: false, response: NextResponse.json({ detail: "forbidden" }, { status: 403 }) };
    }
    return { ok: true, token };
  } catch (err) {
    if (err instanceof TokenExpiredError || err instanceof TokenInvalidError) {
      return {
        ok: false,
        response: NextResponse.json({ detail: "unauthorized" }, { status: 401 }),
      };
    }
    throw err;
  }
}
