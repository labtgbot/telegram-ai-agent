import { describe, expect, it } from "vitest";

import { GET } from "@/app/api/admin/dashboard/route";
import { PERIODS } from "@/lib/dashboard/types";

function makeRequest(period?: string): Request {
  const url = period
    ? `http://localhost/api/admin/dashboard?period=${period}`
    : "http://localhost/api/admin/dashboard";
  return new Request(url, { method: "GET" });
}

describe("GET /api/admin/dashboard", () => {
  it("returns a 200 JSON snapshot for each documented period", async () => {
    for (const period of PERIODS) {
      const response = await GET(makeRequest(period));
      expect(response.status).toBe(200);
      expect(response.headers.get("cache-control")).toBe("no-store");
      const json = (await response.json()) as { period: string; kpis: unknown };
      expect(json.period).toBe(period);
      expect(json.kpis).toBeDefined();
    }
  });

  it("falls back to 7d when the period is missing or invalid", async () => {
    const fallbackDefault = await (await GET(makeRequest())).json();
    const fallbackInvalid = await (await GET(makeRequest("not-a-period"))).json();
    expect(fallbackDefault.period).toBe("7d");
    expect(fallbackInvalid.period).toBe("7d");
  });
});
