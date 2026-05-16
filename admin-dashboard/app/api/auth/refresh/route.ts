import { NextResponse } from "next/server";

import { clearTokens, persistTokens, readRefreshToken } from "@/lib/auth/cookies";
import { serverEnv } from "@/lib/env";

export async function POST(): Promise<NextResponse> {
  const refresh = readRefreshToken();
  if (!refresh) {
    return NextResponse.json({ code: "missing_refresh_token" }, { status: 401 });
  }

  const upstream = await fetch(`${serverEnv().apiBaseUrl}/auth/admin/refresh`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: refresh }),
  });

  if (!upstream.ok) {
    clearTokens();
    const payload = await upstream.json().catch(() => ({}));
    return NextResponse.json(payload, { status: upstream.status });
  }

  const payload = (await upstream.json()) as {
    access_token: string;
    refresh_token: string;
    expires_in: number;
  };
  persistTokens(payload);
  return NextResponse.json({ status: "ok", expires_in: payload.expires_in });
}
