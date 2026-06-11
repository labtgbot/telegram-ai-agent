import { NextResponse } from "next/server";

import { clearTokens, persistTokens, readRefreshToken } from "@/lib/auth/cookies";
import { parseTokenPair } from "@/lib/auth/token-pair";
import { serverEnv } from "@/lib/env";

export async function POST(): Promise<NextResponse> {
  const refresh = await readRefreshToken();
  if (!refresh) {
    return NextResponse.json({ code: "missing_refresh_token" }, { status: 401 });
  }

  const upstream = await fetch(`${serverEnv().apiBaseUrl}/auth/admin/refresh`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: refresh }),
  });

  if (!upstream.ok) {
    await clearTokens();
    const payload = await upstream.json().catch(() => ({}));
    return NextResponse.json(payload, { status: upstream.status });
  }

  const payload = await upstream.json().catch(() => ({}));
  const tokenPair = parseTokenPair(payload);
  if (!tokenPair) {
    return NextResponse.json({ code: "bad_upstream_token_payload" }, { status: 502 });
  }

  await persistTokens(tokenPair);
  return NextResponse.json({ status: "ok", expires_in: tokenPair.expires_in });
}
