import { useQuery, type UseQueryResult } from "@tanstack/react-query";

import { billingKeys } from "@/hooks/queryKeys";
import { fetchTransactions } from "@/services/api/billing";
import type { TransactionType, TransactionsResponse } from "@/types/billing";

export interface UseTransactionsArgs {
  page?: number;
  limit?: number;
  type?: TransactionType | null;
}

/**
 * Paginated transaction history.  `keepPreviousData` keeps the previous
 * page visible while the next one is loading, which makes the "Дальше /
 * Назад" pagination feel instant.
 */
export function useTransactions({
  page = 1,
  limit = 10,
  type = null,
}: UseTransactionsArgs = {}): UseQueryResult<TransactionsResponse, Error> {
  return useQuery<TransactionsResponse, Error>({
    queryKey: billingKeys.transactions(page, limit, type),
    queryFn: () => fetchTransactions({ page, limit, type }),
    staleTime: 10_000,
    placeholderData: (previous) => previous,
  });
}
