import { describe, expect, it } from "vitest";

import {
  DEFAULT_DIRECTION,
  DEFAULT_LIMIT,
  DEFAULT_SORT,
  buildUserListQuery,
  parseUserListQuery,
} from "@/lib/admin-users/url";

describe("admin-users URL helpers", () => {
  it("returns defaults when the query is empty", () => {
    const result = parseUserListQuery({});
    expect(result.sort).toBe(DEFAULT_SORT);
    expect(result.direction).toBe(DEFAULT_DIRECTION);
    expect(result.page).toBe(1);
    expect(result.limit).toBe(DEFAULT_LIMIT);
    expect(result.is_premium).toBeUndefined();
    expect(result.is_banned).toBeUndefined();
  });

  it("parses search, premium and banned filters", () => {
    const result = parseUserListQuery({
      search: "alice",
      is_premium: "true",
      is_banned: "false",
      role: "user",
    });
    expect(result.search).toBe("alice");
    expect(result.is_premium).toBe(true);
    expect(result.is_banned).toBe(false);
    expect(result.role).toBe("user");
  });

  it("falls back to defaults on invalid sort / direction", () => {
    const result = parseUserListQuery({ sort: "password", direction: "weird" });
    expect(result.sort).toBe(DEFAULT_SORT);
    expect(result.direction).toBe(DEFAULT_DIRECTION);
  });

  it("clamps limit and forces page >= 1", () => {
    expect(parseUserListQuery({ limit: "1000" }).limit).toBe(200);
    expect(parseUserListQuery({ limit: "0" }).limit).toBe(1);
    expect(parseUserListQuery({ page: "-3" }).page).toBe(1);
  });

  it("round-trips through buildUserListQuery omitting defaults", () => {
    const qs = buildUserListQuery({
      search: "bob",
      sort: "token_balance",
      direction: "asc",
      page: 3,
      limit: DEFAULT_LIMIT,
      is_banned: true,
    });
    const params = new URLSearchParams(qs);
    expect(params.get("search")).toBe("bob");
    expect(params.get("sort")).toBe("token_balance");
    expect(params.get("direction")).toBe("asc");
    expect(params.get("page")).toBe("3");
    expect(params.has("limit")).toBe(false); // default dropped
    expect(params.get("is_banned")).toBe("true");
  });

  it("drops defaults entirely when serializing", () => {
    expect(buildUserListQuery({ sort: DEFAULT_SORT, direction: DEFAULT_DIRECTION })).toBe("");
  });
});
