export const ROLES = ["super_admin", "support_admin", "analyst", "user", "banned"] as const;
export type Role = (typeof ROLES)[number];

const RANK: Record<Role, number> = {
  banned: -1,
  user: 0,
  analyst: 1,
  support_admin: 2,
  super_admin: 3,
};

export function isAdminRole(role: string | undefined | null): role is Role {
  return role === "analyst" || role === "support_admin" || role === "super_admin";
}

export function roleSatisfies(actual: string | undefined | null, required: Role): boolean {
  if (!actual) return false;
  if (!(actual in RANK)) return false;
  return RANK[actual as Role] >= RANK[required];
}
