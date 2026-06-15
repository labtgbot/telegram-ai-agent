import { timingSafeEqual } from "node:crypto";

import { NextResponse } from "next/server";

import { readCsrfToken } from "@/lib/auth/cookies";
import { CSRF_HEADER_NAME } from "@/lib/auth/csrf";

function equalTokens(expected: string, actual: string): boolean {
  const expectedBuffer = Buffer.from(expected);
  const actualBuffer = Buffer.from(actual);
  return (
    expectedBuffer.length === actualBuffer.length && timingSafeEqual(expectedBuffer, actualBuffer)
  );
}

export async function requireCsrfToken(request: Request): Promise<NextResponse | undefined> {
  const expected = await readCsrfToken();
  const actual = request.headers.get(CSRF_HEADER_NAME);
  if (!expected || !actual || !equalTokens(expected, actual)) {
    return NextResponse.json({ code: "csrf_token_invalid" }, { status: 403 });
  }
  return undefined;
}
