import { NextResponse } from "next/server";

import { requireAdminApiRole } from "@/lib/auth/api-routes";
import { serverEnv } from "@/lib/env";

/**
 * Proxies CSV export from the backend so the browser can trigger a direct
 * download without exposing the access token. The backend route lives at
 * `${apiBaseUrl}/admin/users/export.csv`.
 */
export const dynamic = "force-dynamic";

export async function GET(request: Request): Promise<Response> {
  const auth = await requireAdminApiRole("support_admin");
  if (!auth.ok) return auth.response;

  const inbound = new URL(request.url);
  const upstream = new URL(`${serverEnv().apiBaseUrl}/admin/users/export.csv`);
  for (const [key, value] of inbound.searchParams) {
    upstream.searchParams.set(key, value);
  }

  const response = await fetch(upstream.toString(), {
    headers: { Authorization: `Bearer ${auth.token}` },
    cache: "no-store",
  });

  if (!response.ok) {
    const body = await response.text();
    return new NextResponse(body, {
      status: response.status,
      headers: { "Content-Type": response.headers.get("content-type") ?? "text/plain" },
    });
  }

  const filename = `users-${new Date().toISOString().slice(0, 10)}.csv`;
  return new NextResponse(response.body, {
    status: 200,
    headers: {
      "Content-Type": response.headers.get("content-type") ?? "text/csv; charset=utf-8",
      "Content-Disposition": `attachment; filename="${filename}"`,
      "Cache-Control": "no-store",
    },
  });
}
