import { describe, expect, it } from "vitest";

import { ApiError } from "@/services/apiError";
import { createQueryClient } from "@/services/queryClient";

function getRetryOption() {
  return createQueryClient().getDefaultOptions().queries?.retry;
}

describe("query client retry policy", () => {
  it("does not retry 4xx API errors", () => {
    const retry = getRetryOption();

    expect(typeof retry).toBe("function");
    expect(
      (retry as (failureCount: number, error: unknown) => boolean)(
        0,
        new ApiError("Unauthorized", 401, { detail: "invalid init data" }),
      ),
    ).toBe(false);
  });

  it("retries network and 5xx API errors only once", () => {
    const retry = getRetryOption() as (failureCount: number, error: unknown) => boolean;

    expect(retry(0, new TypeError("Failed to fetch"))).toBe(true);
    expect(retry(1, new TypeError("Failed to fetch"))).toBe(false);
    expect(retry(0, new ApiError("Server error", 502, { detail: "upstream" }))).toBe(true);
    expect(retry(1, new ApiError("Server error", 502, { detail: "upstream" }))).toBe(false);
    expect(retry(0, new Error("Unexpected client error"))).toBe(false);
  });
});
