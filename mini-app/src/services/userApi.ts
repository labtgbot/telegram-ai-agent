import { apiClient, ApiError } from "@/services/apiClient";
import type { ApiClient } from "@/services/apiClient";
import type {
  DataExportRequest,
  DataExportResponse,
  DeleteAccountResponse,
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
    return this.client.get<User>("/users/me");
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

  requestDataExport(payload: DataExportRequest): Promise<DataExportResponse> {
    return this.client.post<DataExportResponse>("/user/data-export", payload);
  }

  deleteAccount(): Promise<DeleteAccountResponse> {
    return this.client.delete<DeleteAccountResponse>("/user/account");
  }
}

export const userApi = new UserApi();

export { ApiError };
