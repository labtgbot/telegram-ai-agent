import { apiClient, ApiError } from "@/services/apiClient";
import type { ApiClient } from "@/services/apiClient";
import type {
  DailyBonusClaim,
  DailyBonusStatus,
  DataExportRequest,
  DataExportResponse,
  DeleteAccountResponse,
  ReferralSummary,
  UsageHistoryPage,
  UsageHistoryQuery,
} from "@/types/profile";
import type { User } from "@/store/useUserStore";

/**
 * Thin typed layer over `apiClient` for profile, settings, history and
 * GDPR endpoints. Centralising the routes here keeps page components free
 * of URL strings and makes it easy to swap implementations under test.
 */
export class UserApi {
  constructor(private readonly client: ApiClient = apiClient) {}

  getProfile(): Promise<User> {
    return this.client.get<User>("/user/me");
  }

  getUsageHistory(query: UsageHistoryQuery = {}): Promise<UsageHistoryPage> {
    return this.client.get<UsageHistoryPage>("/user/usage-history", {
      query: {
        page: query.page,
        limit: query.limit,
        service_type: query.service_type,
      },
    });
  }

  requestDataExport(_payload: DataExportRequest): Promise<DataExportResponse> {
    return this.client.get<DataExportResponse>("/user/me/export");
  }

  deleteAccount(): Promise<DeleteAccountResponse> {
    return this.client.delete<DeleteAccountResponse>("/user/me");
  }

  getReferralSummary(): Promise<ReferralSummary> {
    return this.client.get<ReferralSummary>("/user/referral");
  }

  getDailyBonusStatus(): Promise<DailyBonusStatus> {
    return this.client.get<DailyBonusStatus>("/user/daily-bonus");
  }

  claimDailyBonus(): Promise<DailyBonusClaim> {
    return this.client.post<DailyBonusClaim>("/user/daily-bonus");
  }
}

export const userApi = new UserApi();

export { ApiError };
