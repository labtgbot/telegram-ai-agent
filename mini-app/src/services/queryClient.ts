import { QueryClient } from "@tanstack/react-query";

/**
 * Shared React Query client.
 *
 * Defaults are tuned for a Mini App: short stale times so balance / history
 * stays fresh after a payment, no automatic refetch on window focus (the
 * page is always "focused" inside Telegram), one retry on failure so a
 * flaky mobile connection doesn't surface as a hard error to the user.
 */
export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 15_000,
        gcTime: 5 * 60_000,
        refetchOnWindowFocus: false,
        retry: 1,
      },
      mutations: {
        retry: 0,
      },
    },
  });
}

export const queryClient = createQueryClient();
