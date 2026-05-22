import { useQuery, type UseQueryResult } from "@tanstack/react-query";

import { billingKeys } from "@/hooks/queryKeys";
import { fetchBalance } from "@/services/api/billing";
import type { Balance } from "@/types/billing";

/**
 * Current token balance + premium status + daily-bonus availability.
 *
 * Background refetch is enabled so the balance updates automatically when
 * the user returns from a Telegram Stars payment screen.
 */
export function useBalance(): UseQueryResult<Balance, Error> {
  return useQuery<Balance, Error>({
    queryKey: billingKeys.balance(),
    queryFn: () => fetchBalance(),
    staleTime: 10_000,
  });
}
