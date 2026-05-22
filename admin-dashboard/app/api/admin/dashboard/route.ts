import { NextResponse } from "next/server";

import { buildDashboardSnapshot } from "@/lib/dashboard/mock";
import { isPeriodKey, type PeriodKey } from "@/lib/dashboard/types";

/**
 * `GET /api/v1/admin/dashboard?period=1d|7d|30d|90d`
 *
 * Currently served by an in-memory deterministic generator (the upstream
 * Analytics service is its own ticket).  Once the backend endpoint exists,
 * this handler should proxy to `${apiBaseUrl}/admin/dashboard?period=…`
 * using `createServerApiClient()` and the shape will line up 1:1.
 */
export const dynamic = "force-dynamic";

export async function GET(request: Request): Promise<NextResponse> {
  const url = new URL(request.url);
  const periodParam = url.searchParams.get("period");
  const period: PeriodKey = isPeriodKey(periodParam) ? periodParam : "7d";

  const snapshot = buildDashboardSnapshot(period);

  return NextResponse.json(snapshot, {
    headers: {
      // Discourage caching — the page polls every 30s for "live" updates.
      "Cache-Control": "no-store",
    },
  });
}
