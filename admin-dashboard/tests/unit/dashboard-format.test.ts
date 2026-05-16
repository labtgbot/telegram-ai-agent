import { describe, expect, it } from "vitest";

import {
  deltaTone,
  formatDateShort,
  formatInteger,
  formatNumberCompact,
  formatPercent,
  formatRelative,
  formatStars,
  formatUsd,
} from "@/lib/dashboard/format";

describe("dashboard formatters", () => {
  it("renders compact numbers with K/M suffixes", () => {
    expect(formatNumberCompact(1500)).toBe("1.5K");
    expect(formatNumberCompact(2_400_000)).toBe("2.4M");
  });

  it("renders integers with grouping separators", () => {
    expect(formatInteger(123456)).toBe("123,456");
    expect(formatInteger(0)).toBe("0");
  });

  it("renders USD with no fractional part by default", () => {
    expect(formatUsd(1234)).toBe("$1,234");
    expect(formatUsd(1234.56, { precise: true })).toBe("$1,234.56");
  });

  it("renders Stars with the unicode glyph", () => {
    expect(formatStars(750)).toBe("750 ⭐");
  });

  it("renders percent with one decimal and optional sign", () => {
    expect(formatPercent(5.2)).toBe("5.2%");
    expect(formatPercent(5.2, { sign: true })).toBe("+5.2%");
    expect(formatPercent(-3, { sign: true })).toBe("-3.0%");
    expect(formatPercent(0, { sign: true })).toBe("0.0%");
  });

  it("renders short ISO dates as 'MMM dd' in UTC", () => {
    expect(formatDateShort("2025-05-15")).toBe("May 15");
    expect(formatDateShort("2025-01-01")).toBe("Jan 01");
  });

  it("formats relative timestamps in human language", () => {
    const now = new Date("2025-05-15T12:00:00Z");
    expect(formatRelative("2025-05-15T11:59:30Z", now)).toBe("just now");
    expect(formatRelative("2025-05-15T11:55:00Z", now)).toBe("5m ago");
    expect(formatRelative("2025-05-15T09:00:00Z", now)).toBe("3h ago");
    expect(formatRelative("2025-05-13T12:00:00Z", now)).toBe("2d ago");
  });

  it("classifies tone by delta sign and magnitude", () => {
    expect(deltaTone(2.5)).toBe("up");
    expect(deltaTone(-2.5)).toBe("down");
    expect(deltaTone(0.05)).toBe("flat");
  });
});
