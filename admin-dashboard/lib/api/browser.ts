"use client";

import { ApiClient } from "@/lib/api/client";
import { csrfHeaders } from "@/lib/auth/csrf";
import { publicEnv } from "@/lib/env";

/**
 * Browser-side API client. The access token lives in an HttpOnly cookie
 * (see `lib/auth/cookies.ts`), so we send credentials with each request and
 * route 401 retries through the local `/api/auth/refresh` endpoint.
 */
function createBrowserClient(): ApiClient {
  return new ApiClient({
    baseUrl: publicEnv.apiBaseUrl,
    refreshAccessToken: async () => {
      try {
        const response = await fetch("/api/auth/refresh", {
          method: "POST",
          headers: csrfHeaders(),
          credentials: "include",
        });
        if (!response.ok) return undefined;
        return "refreshed";
      } catch {
        return undefined;
      }
    },
    onAuthLost: (status) => {
      if (typeof window === "undefined") return;
      const url = new URL("/login", window.location.origin);
      url.searchParams.set("from", window.location.pathname);
      if (status === 403) url.searchParams.set("reason", "forbidden");
      window.location.assign(url.toString());
    },
  });
}

let cached: ApiClient | undefined;

export function apiClient(): ApiClient {
  if (!cached) cached = createBrowserClient();
  return cached;
}
