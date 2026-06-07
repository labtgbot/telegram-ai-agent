import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ApiClient } from "@/services/apiClient";
import { UserApi } from "@/services/userApi";

function createClient(): {
  api: UserApi;
  get: ReturnType<typeof vi.fn>;
  post: ReturnType<typeof vi.fn>;
  delete: ReturnType<typeof vi.fn>;
} {
  const get = vi.fn().mockResolvedValue({});
  const post = vi.fn().mockResolvedValue({});
  const delete_ = vi.fn().mockResolvedValue({});
  const client = { get, post, delete: delete_ } as unknown as ApiClient;

  return { api: new UserApi(client), get, post, delete: delete_ };
}

describe("UserApi", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("loads the current profile from the backend /user/me route", async () => {
    const { api, get } = createClient();

    await api.getProfile();

    expect(get).toHaveBeenCalledWith("/user/me");
  });

  it("downloads the GDPR data export with GET /user/me/export", async () => {
    const { api, get, post } = createClient();

    await api.requestDataExport({ email: "ada@example.com" });

    expect(get).toHaveBeenCalledWith("/user/me/export");
    expect(post).not.toHaveBeenCalled();
  });

  it("schedules account deletion with DELETE /user/me", async () => {
    const { api, delete: delete_ } = createClient();

    await api.deleteAccount();

    expect(delete_).toHaveBeenCalledWith("/user/me");
  });
});
