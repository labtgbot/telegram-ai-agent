import { useQuery, type UseQueryResult } from "@tanstack/react-query";

import { billingKeys } from "@/hooks/queryKeys";
import { fetchPackages } from "@/services/api/billing";
import type { PackagesResponse } from "@/types/billing";

/**
 * Token package catalog with current Stars prices.
 *
 * The list is essentially static (driven by an in-code catalog on the
 * backend), so `staleTime` is long: we only need a fresh copy when the
 * Mini App is reloaded.
 */
export function usePackages(): UseQueryResult<PackagesResponse, Error> {
  return useQuery<PackagesResponse, Error>({
    queryKey: billingKeys.packages(),
    queryFn: () => fetchPackages(),
    staleTime: 5 * 60_000,
  });
}
