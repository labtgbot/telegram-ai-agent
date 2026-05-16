import {
  SORT_DIRECTIONS,
  SORT_FIELDS,
  type SortDirection,
  type SortField,
  type UserListQuery,
} from "@/lib/admin-users/types";

/** Default sort the dashboard falls back to when none is in the URL. */
export const DEFAULT_SORT: SortField = "created_at";
export const DEFAULT_DIRECTION: SortDirection = "desc";
export const DEFAULT_LIMIT = 25;

/**
 * Parse query-string values into a `UserListQuery`. Tolerant of stray strings
 * — invalid values fall back to defaults rather than throwing, so a malformed
 * link still renders the page.
 */
export function parseUserListQuery(
  raw: Record<string, string | string[] | undefined>,
): UserListQuery {
  const search = pickString(raw.search) || undefined;
  const role = pickString(raw.role) || undefined;
  const sort = (SORT_FIELDS as readonly string[]).includes(pickString(raw.sort) ?? "")
    ? (pickString(raw.sort) as SortField)
    : DEFAULT_SORT;
  const direction = (SORT_DIRECTIONS as readonly string[]).includes(pickString(raw.direction) ?? "")
    ? (pickString(raw.direction) as SortDirection)
    : DEFAULT_DIRECTION;
  const page = Math.max(1, parseIntSafe(raw.page, 1));
  const limit = clamp(parseIntSafe(raw.limit, DEFAULT_LIMIT), 1, 200);
  return {
    search,
    is_premium: parseBool(raw.is_premium),
    is_banned: parseBool(raw.is_banned),
    role,
    sort,
    direction,
    page,
    limit,
  };
}

/** Serialize a query back to a URL search string. Defaults are dropped. */
export function buildUserListQuery(query: UserListQuery): string {
  const params = new URLSearchParams();
  if (query.search?.trim()) params.set("search", query.search.trim());
  if (typeof query.is_premium === "boolean") params.set("is_premium", String(query.is_premium));
  if (typeof query.is_banned === "boolean") params.set("is_banned", String(query.is_banned));
  if (query.role) params.set("role", query.role);
  if (query.sort && query.sort !== DEFAULT_SORT) params.set("sort", query.sort);
  if (query.direction && query.direction !== DEFAULT_DIRECTION)
    params.set("direction", query.direction);
  if (query.page && query.page > 1) params.set("page", String(query.page));
  if (query.limit && query.limit !== DEFAULT_LIMIT) params.set("limit", String(query.limit));
  return params.toString();
}

function pickString(value: string | string[] | undefined): string | undefined {
  if (Array.isArray(value)) return value[0];
  return value;
}

function parseIntSafe(value: string | string[] | undefined, fallback: number): number {
  const raw = pickString(value);
  if (raw === undefined) return fallback;
  const num = Number.parseInt(raw, 10);
  if (Number.isNaN(num)) return fallback;
  return num;
}

function parseBool(value: string | string[] | undefined): boolean | undefined {
  const raw = pickString(value);
  if (raw === undefined || raw === "") return undefined;
  if (raw === "true" || raw === "1") return true;
  if (raw === "false" || raw === "0") return false;
  return undefined;
}

function clamp(value: number, min: number, max: number): number {
  if (value < min) return min;
  if (value > max) return max;
  return value;
}
