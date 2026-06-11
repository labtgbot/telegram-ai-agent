import { QueryClient } from "@tanstack/react-query";

import { ApiError } from "@/services/apiError";

export function shouldRetryQuery(failureCount: number, error: unknown): boolean {
  if (failureCount >= 1) {
    return false;
  }
  if (error instanceof ApiError) {
    return error.status >= 500;
  }
  return error instanceof TypeError;
}

/**
 * Shared React Query client.
 *
 * Defaults are tuned for a Mini App: short stale times so balance / history
 * stays fresh after a payment, no automatic refetch on window focus (the
 * page is always "focused" inside Telegram), one retry for network/server
 * failures so a flaky mobile connection doesn't surface as a hard error.
 */
export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 15_000,
        gcTime: 5 * 60_000,
        refetchOnWindowFocus: false,
        retry: shouldRetryQuery,
      },
      mutations: {
        retry: 0,
      },
    },
  });
}

export const queryClient = createQueryClient();
