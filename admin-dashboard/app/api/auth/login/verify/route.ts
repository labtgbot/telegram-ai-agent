import { NextResponse } from "next/server";
import { z } from "zod";

import { persistTokens } from "@/lib/auth/cookies";
import { parseTokenPair } from "@/lib/auth/token-pair";
import { serverEnv } from "@/lib/env";

const schema = z.object({
  telegram_id: z.number().int().positive(),
  code: z.string().min(4).max(10),
  totp_code: z.string().min(4).max(10).optional(),
});

export async function POST(request: Request): Promise<NextResponse> {
  const json = await request.json().catch(() => null);
  const parsed = schema.safeParse(json);
  if (!parsed.success) {
    return NextResponse.json(
      { code: "bad_request", detail: parsed.error.format() },
      { status: 400 },
    );
  }

  const upstream = await fetch(`${serverEnv().apiBaseUrl}/auth/admin/login/verify`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(parsed.data),
  });

  const payload = await upstream.json().catch(() => ({}));
  if (!upstream.ok) {
    return NextResponse.json(payload, { status: upstream.status });
  }

  const tokenPair = parseTokenPair(payload);
  if (!tokenPair) {
    return NextResponse.json({ code: "bad_upstream_token_payload" }, { status: 502 });
  }

  await persistTokens(tokenPair);

  return NextResponse.json({ status: "ok", expires_in: tokenPair.expires_in });
}
