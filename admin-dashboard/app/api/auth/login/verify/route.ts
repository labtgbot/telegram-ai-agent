import { NextResponse } from "next/server";
import { z } from "zod";

import { persistTokens } from "@/lib/auth/cookies";
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
    return NextResponse.json({ code: "bad_request", detail: parsed.error.format() }, { status: 400 });
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

  persistTokens({
    access_token: payload.access_token,
    refresh_token: payload.refresh_token,
    expires_in: payload.expires_in,
  });

  return NextResponse.json({ status: "ok", expires_in: payload.expires_in });
}
