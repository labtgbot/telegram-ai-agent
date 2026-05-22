import { NextResponse } from "next/server";

import { readAccessToken } from "@/lib/auth/cookies";
import { serverEnv } from "@/lib/env";

/**
 * Proxies the analytics revenue CSV export from the backend so the
 * browser can trigger a direct download without ever seeing the
 * HttpOnly access token. The backend route lives at
 * `${apiBaseUrl}/admin/analytics/export.csv` and writes its own audit
 * row before returning the body.
 */
export const dynamic = "force-dynamic";

export async function GET(request: Request): Promise<Response> {
  const token = readAccessToken();
  if (!token) {
    return NextResponse.json({ detail: "unauthorized" }, { status: 401 });
  }

  const inbound = new URL(request.url);
  const upstream = new URL(`${serverEnv().apiBaseUrl}/admin/analytics/export.csv`);
  for (const [key, value] of inbound.searchParams) {
    upstream.searchParams.set(key, value);
  }

  const response = await fetch(upstream.toString(), {
    headers: { Authorization: `Bearer ${token}` },
    cache: "no-store",
  });

  if (!response.ok) {
    const body = await response.text();
    return new NextResponse(body, {
      status: response.status,
      headers: { "Content-Type": response.headers.get("content-type") ?? "text/plain" },
    });
  }

  const disposition =
    response.headers.get("content-disposition") ??
    `attachment; filename="revenue-${new Date().toISOString().slice(0, 10)}.csv"`;
  return new NextResponse(response.body, {
    status: 200,
    headers: {
      "Content-Type": response.headers.get("content-type") ?? "text/csv; charset=utf-8",
      "Content-Disposition": disposition,
      "Cache-Control": "no-store",
    },
  });
}
