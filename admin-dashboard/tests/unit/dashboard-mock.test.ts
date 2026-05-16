import { describe, expect, it } from "vitest";

import { buildDashboardSnapshot } from "@/lib/dashboard/mock";
import { PERIODS } from "@/lib/dashboard/types";

const ANCHOR = new Date("2025-05-15T12:34:56.000Z");

describe("buildDashboardSnapshot", () => {
  it("returns a stable snapshot for identical (period, day) pairs", () => {
    const a = buildDashboardSnapshot("7d", { now: ANCHOR });
    const b = buildDashboardSnapshot("7d", { now: ANCHOR });
    expect(a).toEqual(b);
  });

  it("varies between periods so the UI tabs change visibly", () => {
    const seven = buildDashboardSnapshot("7d", { now: ANCHOR });
    const ninety = buildDashboardSnapshot("90d", { now: ANCHOR });
    expect(seven.kpis.tokens.sold.value).not.toBe(ninety.kpis.tokens.sold.value);
    expect(seven.charts.usage_by_service[0]?.tokens).not.toBe(
      ninety.charts.usage_by_service[0]?.tokens,
    );
  });

  it("emits exactly 30 daily points for the revenue chart", () => {
    const snapshot = buildDashboardSnapshot("30d", { now: ANCHOR });
    expect(snapshot.charts.revenue_30d).toHaveLength(30);
    const dates = snapshot.charts.revenue_30d.map((point) => point.date);
    expect(dates[0]).toBe("2025-04-16");
    expect(dates.at(-1)).toBe("2025-05-15");
    for (const point of snapshot.charts.revenue_30d) {
      expect(point.usd).toBeGreaterThanOrEqual(0);
    }
  });

  it("emits exactly 7 points for the activity chart, ending today", () => {
    const snapshot = buildDashboardSnapshot("7d", { now: ANCHOR });
    expect(snapshot.charts.activity_7d).toHaveLength(7);
    expect(snapshot.charts.activity_7d.at(-1)?.date).toBe("2025-05-15");
  });

  it("returns the three required service slices with positive token counts", () => {
    const snapshot = buildDashboardSnapshot("30d", { now: ANCHOR });
    const services = snapshot.charts.usage_by_service.map((slice) => slice.service);
    expect(services.sort()).toEqual(["image", "text", "video"]);
    for (const slice of snapshot.charts.usage_by_service) {
      expect(slice.tokens).toBeGreaterThan(0);
      expect(slice.requests).toBeGreaterThan(0);
    }
  });

  it("populates latest transactions sorted newest first", () => {
    const snapshot = buildDashboardSnapshot("7d", { now: ANCHOR });
    expect(snapshot.latest_transactions.length).toBeGreaterThan(0);
    const dates = snapshot.latest_transactions.map((row) => row.created_at);
    const sorted = [...dates].sort((a, b) => b.localeCompare(a));
    expect(dates).toEqual(sorted);
  });

  it("populates new users with telegram ids and timestamps", () => {
    const snapshot = buildDashboardSnapshot("7d", { now: ANCHOR });
    expect(snapshot.new_users.length).toBeGreaterThan(0);
    for (const row of snapshot.new_users) {
      expect(row.telegram_id).toBeGreaterThan(0);
      expect(Date.parse(row.created_at)).not.toBeNaN();
    }
  });

  it("supports every documented period without crashing", () => {
    for (const period of PERIODS) {
      const snapshot = buildDashboardSnapshot(period, { now: ANCHOR });
      expect(snapshot.period).toBe(period);
      expect(snapshot.kpis.users.total.value).toBeGreaterThan(0);
    }
  });

  it("computes a previous value consistent with the delta percentage", () => {
    const snapshot = buildDashboardSnapshot("30d", { now: ANCHOR });
    const total = snapshot.kpis.users.total;
    const expectedPrev = Math.round(total.value / (1 + total.delta_pct / 100));
    expect(total.previous).toBe(expectedPrev);
  });
});
