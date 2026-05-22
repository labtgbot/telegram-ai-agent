import { useQuery, type UseQueryResult } from "@tanstack/react-query";

import { billingKeys } from "@/hooks/queryKeys";
import { fetchReferral } from "@/services/api/billing";
import type { ReferralInfo } from "@/types/billing";

/**
 * Referral code + shareable bot link for the current user.  The link
 * never changes for a given user, so the cache lives for a long time.
 */
export function useReferral(): UseQueryResult<ReferralInfo, Error> {
  return useQuery<ReferralInfo, Error>({
    queryKey: billingKeys.referral(),
    queryFn: () => fetchReferral(),
    staleTime: 30 * 60_000,
  });
}
