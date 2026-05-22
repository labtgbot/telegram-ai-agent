import "server-only";

import { readAccessToken, readRefreshToken, persistTokens, clearTokens } from "@/lib/auth/cookies";
import { ApiClient } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import { serverEnv } from "@/lib/env";

/**
 * Server-side API client used by route handlers and server components. It
 * mirrors the browser client but pulls the access token from HttpOnly cookies
 * and refreshes them in-place.
 */
export function createServerApiClient(): ApiClient {
  return new ApiClient({
    baseUrl: serverEnv().apiBaseUrl,
    getAccessToken: () => readAccessToken(),
    refreshAccessToken: async () => {
      const refresh = readRefreshToken();
      if (!refresh) return undefined;
      try {
        const response = await fetch(`${serverEnv().apiBaseUrl}/auth/admin/refresh`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ refresh_token: refresh }),
        });
        if (!response.ok) {
          clearTokens();
          return undefined;
        }
        const payload = (await response.json()) as {
          access_token: string;
          refresh_token: string;
          expires_in: number;
        };
        persistTokens(payload);
        return payload.access_token;
      } catch {
        clearTokens();
        return undefined;
      }
    },
    onAuthLost: (status) => {
      if (status === 401) clearTokens();
    },
  });
}

export { ApiError };
