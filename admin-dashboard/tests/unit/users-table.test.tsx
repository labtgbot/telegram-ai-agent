import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { UsersTable } from "@/components/admin-users/users-table";
import type { AdminUserSummary } from "@/lib/admin-users/types";

const push = vi.fn();
let currentParams = new URLSearchParams();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
  useSearchParams: () => currentParams,
}));

function row(overrides: Partial<AdminUserSummary> = {}): AdminUserSummary {
  return {
    id: 1,
    telegram_id: 100,
    username: "alice",
    first_name: "Alice",
    last_name: null,
    language_code: "en",
    role: "user",
    is_premium: false,
    is_banned: false,
    ban_reason: null,
    banned_until: null,
    token_balance: 1000,
    total_tokens_purchased: 0,
    total_tokens_spent: 250,
    total_requests: 12,
    referral_code: "AU-100",
    referred_by: null,
    created_at: "2026-05-01T00:00:00Z",
    last_active_at: "2026-05-15T00:00:00Z",
    last_login_at: null,
    ...overrides,
  };
}

describe("<UsersTable />", () => {
  beforeEach(() => {
    push.mockReset();
    currentParams = new URLSearchParams();
  });
  afterEach(() => cleanup());

  it("renders rows with badges for premium and banned", () => {
    render(
      <UsersTable
        rows={[
          row({ id: 1, username: "alice", first_name: "Alice", is_premium: true }),
          row({ id: 2, username: "bob", first_name: "Bob", is_banned: true }),
        ]}
        sort="created_at"
        direction="desc"
      />,
    );
    expect(screen.getByText("Alice")).toBeInTheDocument();
    expect(screen.getByText("Bob")).toBeInTheDocument();
    expect(screen.getByText("premium")).toBeInTheDocument();
    expect(screen.getByText("banned")).toBeInTheDocument();
  });

  it("navigates with new sort when a sortable column header is clicked", async () => {
    const user = userEvent.setup();
    render(
      <UsersTable rows={[row()]} sort="created_at" direction="desc" />,
    );
    await user.click(screen.getByRole("button", { name: /balance/i }));
    expect(push).toHaveBeenCalledWith("/users?sort=token_balance&direction=desc");
  });

  it("toggles direction when clicking the active sort column twice", async () => {
    const user = userEvent.setup();
    currentParams = new URLSearchParams("sort=token_balance&direction=desc");
    render(
      <UsersTable rows={[row()]} sort="token_balance" direction="desc" />,
    );
    await user.click(screen.getByRole("button", { name: /balance/i }));
    expect(push).toHaveBeenCalledWith("/users?sort=token_balance&direction=asc");
  });

  it("opens the selected user when a row is clicked", async () => {
    const user = userEvent.setup();
    render(
      <UsersTable rows={[row({ id: 42 })]} sort="created_at" direction="desc" />,
    );
    await user.click(screen.getByText("Alice"));
    expect(push).toHaveBeenCalledWith("/users?user=42");
  });

  it("shows an empty-state message when there are no rows", () => {
    render(<UsersTable rows={[]} sort="created_at" direction="desc" />);
    expect(screen.getByText(/No users match/i)).toBeInTheDocument();
  });
});
