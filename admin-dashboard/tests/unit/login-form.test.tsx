import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { LoginForm } from "@/components/auth/login-form";

const replace = vi.fn();
const refresh = vi.fn();
let currentParams = new URLSearchParams();
const fetchMock = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace, refresh }),
  useSearchParams: () => currentParams,
}));

function mockSuccessfulLogin() {
  fetchMock
    .mockResolvedValueOnce({
      ok: true,
      json: async () => ({ delivery: "response", ttl_seconds: 60, code: "654321" }),
    })
    .mockResolvedValueOnce({
      ok: true,
      json: async () => ({}),
    });
}

async function completeLogin() {
  const user = userEvent.setup();
  render(<LoginForm />);

  await user.type(screen.getByLabelText(/Telegram ID/i), "123456789");
  await user.click(screen.getByRole("button", { name: /Send code/i }));
  expect(await screen.findByText(/Dev code:/i)).toBeInTheDocument();

  await user.type(screen.getByLabelText(/One-time code/i), "654321");
  await user.click(screen.getByRole("button", { name: /Sign in/i }));
  await waitFor(() => expect(replace).toHaveBeenCalled());
}

describe("<LoginForm /> post-login redirect", () => {
  beforeEach(() => {
    replace.mockReset();
    refresh.mockReset();
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
    currentParams = new URLSearchParams();
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it.each(["//evil.com", "/\\evil.com"])(
    "falls back to the dashboard for unsafe from=%s",
    async (from) => {
      currentParams.set("from", from);
      mockSuccessfulLogin();

      await completeLogin();

      expect(replace).toHaveBeenCalledWith("/dashboard");
      expect(refresh).toHaveBeenCalled();
    },
  );

  it("honours same-origin relative paths", async () => {
    currentParams.set("from", "/users?sort=created_at#latest");
    mockSuccessfulLogin();

    await completeLogin();

    expect(replace).toHaveBeenCalledWith("/users?sort=created_at#latest");
    expect(refresh).toHaveBeenCalled();
  });
});
