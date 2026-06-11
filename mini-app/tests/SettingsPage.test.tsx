import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { SettingsPage } from "@/pages/SettingsPage";
import { useSettingsStore } from "@/store/useSettingsStore";
import { useUserStore } from "@/store/useUserStore";
import { useThemeStore } from "@/store/useThemeStore";

vi.mock("@/services/userApi", () => ({
  userApi: {
    requestDataExport: vi.fn(),
    deleteAccount: vi.fn(),
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

vi.mock("@/lib/sentry", () => ({
  Sentry: {
    captureException: vi.fn(),
  },
}));

import { userApi } from "@/services/userApi";
import { Sentry } from "@/lib/sentry";

const requestExportMock = vi.mocked(userApi.requestDataExport);
const deleteAccountMock = vi.mocked(userApi.deleteAccount);
const captureExceptionMock = vi.mocked(Sentry.captureException);

beforeEach(() => {
  window.localStorage.clear();
  useSettingsStore.getState().reset();
  useUserStore.getState().reset();
  useThemeStore.setState({ scheme: "light", themeParams: {} });
  requestExportMock.mockReset();
  deleteAccountMock.mockReset();
  captureExceptionMock.mockReset();
});

describe("SettingsPage", () => {
  it("toggles notifications and persists preference", async () => {
    render(<SettingsPage />);
    const toggle = screen.getByRole("switch", { name: "Notifications" });
    expect(toggle).toBeChecked();
    await userEvent.click(toggle);
    expect(toggle).not.toBeChecked();
    expect(useSettingsStore.getState().notificationsEnabled).toBe(false);
  });

  it("changes language preference", async () => {
    render(<SettingsPage />);
    const select = screen.getByLabelText("Language") as HTMLSelectElement;
    await userEvent.selectOptions(select, "ru");
    expect(useSettingsStore.getState().language).toBe("ru");
  });

  it("changes AI response size", async () => {
    render(<SettingsPage />);
    const select = screen.getByLabelText("AI response size") as HTMLSelectElement;
    await userEvent.selectOptions(select, "long");
    expect(useSettingsStore.getState().aiResponseSize).toBe("long");
  });

  it("validates email before requesting export", async () => {
    render(<SettingsPage />);
    await userEvent.type(screen.getByLabelText("Email"), "not-an-email");
    await userEvent.click(screen.getByRole("button", { name: "Request export" }));
    expect(requestExportMock).not.toHaveBeenCalled();
    expect(screen.getByTestId("export-status")).toHaveTextContent(/valid email/i);
  });

  it("submits a valid export request and shows confirmation", async () => {
    requestExportMock.mockResolvedValue({
      schema_version: "1.0",
      generated_at: "2026-06-07T00:00:00Z",
      user: {},
      transactions: [],
      subscriptions: [],
      chat_threads: [],
      chat_messages: [],
      daily_bonus_claims: [],
      referrals_summary: { count: 0 },
      notes: [],
    });
    render(<SettingsPage />);
    await userEvent.type(screen.getByLabelText("Email"), "me@example.com");
    await userEvent.click(screen.getByRole("button", { name: "Request export" }));
    await waitFor(() =>
      expect(requestExportMock).toHaveBeenCalledWith({ email: "me@example.com" }),
    );
    expect(screen.getByTestId("export-status")).toHaveTextContent(/Export requested/i);
  });

  it("shows an error message when the export request fails", async () => {
    requestExportMock.mockRejectedValue(new Error("boom"));
    render(<SettingsPage />);
    await userEvent.type(screen.getByLabelText("Email"), "me@example.com");
    await userEvent.click(screen.getByRole("button", { name: "Request export" }));
    await waitFor(() =>
      expect(screen.getByTestId("export-status")).toHaveTextContent(/Could not request/i),
    );
  });

  it("shows an auth-specific message when export is unauthorized", async () => {
    const { ApiError } = await import("@/services/userApi");
    requestExportMock.mockRejectedValue(new ApiError("Unauthorized", 401, { detail: "bad auth" }));

    render(<SettingsPage />);
    await userEvent.type(screen.getByLabelText("Email"), "me@example.com");
    await userEvent.click(screen.getByRole("button", { name: "Request export" }));

    await waitFor(() =>
      expect(screen.getByTestId("export-status")).toHaveTextContent(/session expired/i),
    );
    expect(captureExceptionMock).not.toHaveBeenCalled();
  });

  it("reports unexpected export failures to Sentry", async () => {
    const failure = new Error("network down");
    requestExportMock.mockRejectedValue(failure);

    render(<SettingsPage />);
    await userEvent.type(screen.getByLabelText("Email"), "me@example.com");
    await userEvent.click(screen.getByRole("button", { name: "Request export" }));

    await waitFor(() =>
      expect(screen.getByTestId("export-status")).toHaveTextContent(/could not request/i),
    );
    expect(captureExceptionMock).toHaveBeenCalledWith(failure);
  });

  it("opens the delete-account confirm dialog and requires the typed token", async () => {
    deleteAccountMock.mockResolvedValue({
      request_id: 7,
      status: "pending",
      requested_at: "2026-06-07T00:00:00Z",
      scheduled_for: "2026-07-07T00:00:00Z",
      detail: "deletion_scheduled",
    });
    render(<SettingsPage />);

    await userEvent.click(screen.getByRole("button", { name: "Delete my account" }));
    const dialog = await screen.findByRole("dialog");
    const confirmBtn = within(dialog).getByRole("button", { name: "Delete my account" });
    expect(confirmBtn).toBeDisabled();

    await userEvent.type(within(dialog).getByPlaceholderText("DELETE"), "DELETE");
    expect(confirmBtn).toBeEnabled();
    await userEvent.click(confirmBtn);

    await waitFor(() => expect(deleteAccountMock).toHaveBeenCalledOnce());
    expect(useUserStore.getState().user).toBeNull();
  });

  it("cancels delete dialog without calling API", async () => {
    render(<SettingsPage />);
    await userEvent.click(screen.getByRole("button", { name: "Delete my account" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(deleteAccountMock).not.toHaveBeenCalled();
  });

  it("shows an auth-specific message when account deletion is forbidden", async () => {
    const { ApiError } = await import("@/services/userApi");
    deleteAccountMock.mockRejectedValue(new ApiError("Forbidden", 403, { detail: "forbidden" }));

    render(<SettingsPage />);
    await userEvent.click(screen.getByRole("button", { name: "Delete my account" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.type(within(dialog).getByPlaceholderText("DELETE"), "DELETE");
    await userEvent.click(within(dialog).getByRole("button", { name: "Delete my account" }));

    await waitFor(() =>
      expect(screen.getByTestId("delete-status")).toHaveTextContent(/session expired/i),
    );
    expect(captureExceptionMock).not.toHaveBeenCalled();
  });
});
