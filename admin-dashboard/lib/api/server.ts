import "server-only";

import { readAccessToken, readRefreshToken, persistTokens, clearTokens } from "@/lib/auth/cookies";
import { ApiClient } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import { parseTokenPair } from "@/lib/auth/token-pair";
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
      const refresh = await readRefreshToken();
      if (!refresh) return undefined;
      try {
        const response = await fetch(`${serverEnv().apiBaseUrl}/auth/admin/refresh`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ refresh_token: refresh }),
        });
        if (!response.ok) {
          await clearTokens();
          return undefined;
        }
        const payload = await response.json().catch(() => ({}));
        const tokenPair = parseTokenPair(payload);
        if (!tokenPair) {
          await clearTokens();
          return undefined;
        }
        await persistTokens(tokenPair);
        return tokenPair.access_token;
      } catch {
        await clearTokens();
        return undefined;
      }
    },
    onAuthLost: async (status) => {
      if (status === 401) await clearTokens();
    },
  });
}

export { ApiError };
