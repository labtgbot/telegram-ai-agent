import { randomBytes } from "node:crypto";

import { cookies } from "next/headers";

import { CSRF_COOKIE_NAME } from "@/lib/auth/csrf";
import { COOKIE_NAMES } from "@/lib/auth/tokens";

export interface TokenPair {
  access_token: string;
  refresh_token: string;
  /** Seconds until the access token expires. */
  expires_in: number;
}

const FOURTEEN_DAYS = 14 * 24 * 60 * 60;

function newCsrfToken(): string {
  return randomBytes(32).toString("base64url");
}

/**
 * Store both tokens as HttpOnly cookies so the browser keeps the secrets but
 * server components / middleware can read them. The access cookie expires
 * with the JWT; the refresh cookie lives long enough to cover an idle admin.
 */
export async function persistTokens(pair: TokenPair): Promise<void> {
  const store = await cookies();
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
  store.set(CSRF_COOKIE_NAME, newCsrfToken(), {
    httpOnly: false,
    sameSite: "strict",
    secure,
    path: "/",
    maxAge: FOURTEEN_DAYS,
  });
}

export async function clearTokens(): Promise<void> {
  const store = await cookies();
  store.delete(COOKIE_NAMES.access);
  store.delete(COOKIE_NAMES.refresh);
  store.delete(COOKIE_NAMES.csrf);
}

export async function readAccessToken(): Promise<string | undefined> {
  return (await cookies()).get(COOKIE_NAMES.access)?.value;
}

export async function readRefreshToken(): Promise<string | undefined> {
  return (await cookies()).get(COOKIE_NAMES.refresh)?.value;
}

export async function readCsrfToken(): Promise<string | undefined> {
  return (await cookies()).get(COOKIE_NAMES.csrf)?.value;
}
