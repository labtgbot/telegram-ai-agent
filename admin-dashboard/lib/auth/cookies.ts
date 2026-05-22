import { cookies } from "next/headers";

import { COOKIE_NAMES } from "@/lib/auth/tokens";

export interface TokenPair {
  access_token: string;
  refresh_token: string;
  /** Seconds until the access token expires. */
  expires_in: number;
}

const FOURTEEN_DAYS = 14 * 24 * 60 * 60;

/**
 * Store both tokens as HttpOnly cookies so the browser keeps the secrets but
 * server components / middleware can read them. The access cookie expires
 * with the JWT; the refresh cookie lives long enough to cover an idle admin.
 */
export function persistTokens(pair: TokenPair): void {
  const store = cookies();
  const secure = process.env.NODE_ENV === "production";
  store.set(COOKIE_NAMES.access, pair.access_token, {
    httpOnly: true,
    sameSite: "lax",
    secure,
    path: "/",
    maxAge: pair.expires_in,
  });
  store.set(COOKIE_NAMES.refresh, pair.refresh_token, {
    httpOnly: true,
    sameSite: "lax",
    secure,
    path: "/",
    maxAge: FOURTEEN_DAYS,
  });
}

export function clearTokens(): void {
  const store = cookies();
  store.delete(COOKIE_NAMES.access);
  store.delete(COOKIE_NAMES.refresh);
}

export function readAccessToken(): string | undefined {
  return cookies().get(COOKIE_NAMES.access)?.value;
}

export function readRefreshToken(): string | undefined {
  return cookies().get(COOKIE_NAMES.refresh)?.value;
}
