import { NextResponse } from "next/server";

import { clearTokens } from "@/lib/auth/cookies";

export async function POST(): Promise<NextResponse> {
  await clearTokens();
  return NextResponse.json({ status: "ok" });
}
