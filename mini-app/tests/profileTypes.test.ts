import { describe, expect, it } from "vitest";

import { normalizeServiceType } from "@/types/profile";

describe("normalizeServiceType", () => {
  it("maps known service types in lower-case", () => {
    expect(normalizeServiceType("text")).toBe("text");
    expect(normalizeServiceType("IMAGE")).toBe("image");
    expect(normalizeServiceType("Video")).toBe("video");
  });

  it("falls back to other for unknown or empty values", () => {
    expect(normalizeServiceType(null)).toBe("other");
    expect(normalizeServiceType(undefined)).toBe("other");
    expect(normalizeServiceType("")).toBe("other");
    expect(normalizeServiceType("translate")).toBe("other");
  });
});
