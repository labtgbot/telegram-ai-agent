import { NextResponse } from "next/server";
import { z } from "zod";

import { serverEnv } from "@/lib/env";

const schema = z.object({
  telegram_id: z.number().int().positive(),
});

export async function POST(request: Request): Promise<NextResponse> {
  const json = await request.json().catch(() => null);
  const parsed = schema.safeParse(json);
  if (!parsed.success) {
    return NextResponse.json({ code: "bad_request", detail: parsed.error.format() }, { status: 400 });
  }

  const upstream = await fetch(`${serverEnv().apiBaseUrl}/auth/admin/login/request`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(parsed.data),
  });

  const body = await upstream.json().catch(() => ({}));
  return NextResponse.json(body, { status: upstream.status });
}
