import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import { ProfilePage } from "@/pages/ProfilePage";
import { useUserStore } from "@/store/useUserStore";
import { useSettingsStore } from "@/store/useSettingsStore";
import type { User } from "@/store/useUserStore";

vi.mock("@/services/userApi", () => ({
  userApi: {
    getProfile: vi.fn(),
  },
  ApiError: class ApiError extends Error {
    status: number;
    body: unknown;
    constructor(message: string, status: number, body: unknown) {
      super(message);
      this.status = status;
      this.body = body;
    }
  },
}));

import { userApi } from "@/services/userApi";
const getProfileMock = vi.mocked(userApi.getProfile);

function seedUser(overrides: Partial<User> = {}): void {
  useUserStore.getState().setUser({
    id: 11,
    telegram_id: 200,
    username: "alice",
    first_name: "Alice",
    last_name: "Wonder",
    language_code: "en",
    role: "user",
    referral_code: "ALICE",
    is_premium: true,
    is_banned: false,
    photo_url: "https://cdn.example.com/alice.png",
    premium_expires_at: "2030-01-15T00:00:00Z",
    created_at: "2024-03-04T00:00:00Z",
    totp_enabled: false,
    ...overrides,
  });
}

describe("ProfilePage", () => {
  beforeEach(() => {
    useUserStore.getState().reset();
    useSettingsStore.getState().reset();
    getProfileMock.mockReset();
    getProfileMock.mockResolvedValue({
      id: 11,
      telegram_id: 200,
      username: "alice",
      first_name: "Alice",
      last_name: "Wonder",
      language_code: "en",
      role: "user",
      referral_code: "ALICE",
      is_premium: true,
      is_banned: false,
      photo_url: "https://cdn.example.com/alice.png",
      premium_expires_at: "2030-01-15T00:00:00Z",
      created_at: "2024-03-04T00:00:00Z",
      totp_enabled: false,
    } satisfies User);
  });

  it("shows nickname, username, language, premium and registration date", async () => {
    seedUser();
    render(
      <MemoryRouter>
        <ProfilePage />
      </MemoryRouter>,
    );

    expect(screen.getByTestId("profile-name")).toHaveTextContent("Alice Wonder");
    expect(screen.getByTestId("profile-username")).toHaveTextContent("@alice");
    expect(screen.getByTestId("row-language")).toHaveTextContent("en");
    expect(screen.getByTestId("row-premium").textContent).toContain("Expires");
    expect(screen.getByTestId("row-member-since").textContent).toContain("2024");
    expect(screen.getByTestId("avatar-image")).toHaveAttribute(
      "src",
      "https://cdn.example.com/alice.png",
    );

    await waitFor(() => expect(getProfileMock).toHaveBeenCalled());
  });

  it("renders an empty state when no user is loaded yet", () => {
    render(
      <MemoryRouter>
        <ProfilePage />
      </MemoryRouter>,
    );
    expect(screen.getByTestId("profile-empty")).toBeInTheDocument();
  });

  it("uses initials when no photo_url is provided", async () => {
    seedUser({ photo_url: null });
    render(
      <MemoryRouter>
        <ProfilePage />
      </MemoryRouter>,
    );
    expect(screen.getByTestId("avatar-fallback")).toHaveTextContent("AW");
    await waitFor(() => expect(getProfileMock).toHaveBeenCalled());
  });

  it("shows Inactive when user is not premium", async () => {
    seedUser({ is_premium: false, premium_expires_at: null });
    render(
      <MemoryRouter>
        <ProfilePage />
      </MemoryRouter>,
    );
    expect(screen.getByTestId("row-premium")).toHaveTextContent("Inactive");
    await waitFor(() => expect(getProfileMock).toHaveBeenCalled());
  });
});
