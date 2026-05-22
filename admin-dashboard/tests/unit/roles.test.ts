import { describe, expect, it } from "vitest";

import { isAdminRole, roleSatisfies } from "@/lib/auth/roles";

describe("roles", () => {
  it("isAdminRole matches the three admin tiers", () => {
    expect(isAdminRole("analyst")).toBe(true);
    expect(isAdminRole("support_admin")).toBe(true);
    expect(isAdminRole("super_admin")).toBe(true);
  });

  it("isAdminRole rejects regular users and unknown roles", () => {
    expect(isAdminRole("user")).toBe(false);
    expect(isAdminRole("banned")).toBe(false);
    expect(isAdminRole("guest")).toBe(false);
    expect(isAdminRole(undefined)).toBe(false);
    expect(isAdminRole(null)).toBe(false);
  });

  it("roleSatisfies is hierarchical: higher roles satisfy lower requirements", () => {
    expect(roleSatisfies("super_admin", "analyst")).toBe(true);
    expect(roleSatisfies("super_admin", "support_admin")).toBe(true);
    expect(roleSatisfies("super_admin", "super_admin")).toBe(true);
    expect(roleSatisfies("support_admin", "analyst")).toBe(true);
    expect(roleSatisfies("support_admin", "super_admin")).toBe(false);
    expect(roleSatisfies("analyst", "support_admin")).toBe(false);
    expect(roleSatisfies("user", "analyst")).toBe(false);
  });

  it("roleSatisfies is safe for unexpected inputs", () => {
    expect(roleSatisfies(undefined, "analyst")).toBe(false);
    expect(roleSatisfies("ghost", "analyst")).toBe(false);
  });
});
