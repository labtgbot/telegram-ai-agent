import { NextResponse } from "next/server";

import { clearTokens, readRefreshToken } from "@/lib/auth/cookies";
import { requireCsrfToken } from "@/lib/auth/csrf-server";
import { serverEnv } from "@/lib/env";

export async function POST(request: Request): Promise<NextResponse> {
  const csrf = await requireCsrfToken(request);
  if (csrf) return csrf;

  const refresh = await readRefreshToken();
  if (refresh) {
    await fetch(`${serverEnv().apiBaseUrl}/auth/admin/logout`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: refresh }),
    }).catch(() => undefined);
  }

  await clearTokens();
  return NextResponse.json({ status: "ok" });
}
