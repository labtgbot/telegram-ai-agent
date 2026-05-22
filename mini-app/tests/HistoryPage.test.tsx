import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { HistoryPage } from "@/pages/HistoryPage";
import { useSettingsStore } from "@/store/useSettingsStore";
import { useUserStore } from "@/store/useUserStore";
import type { UsageHistoryPage } from "@/types/profile";

vi.mock("@/services/userApi", () => ({
  userApi: {
    getUsageHistory: vi.fn(),
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

const getHistoryMock = vi.mocked(userApi.getUsageHistory);

function page(overrides: Partial<UsageHistoryPage> = {}): UsageHistoryPage {
  return {
    items: [
      {
        id: 1,
        service_type: "text",
        tokens_consumed: 120,
        response_status: "success",
        processing_time_ms: 312,
        request_params: null,
        created_at: "2026-04-01T10:00:00Z",
      },
      {
        id: 2,
        service_type: "image",
        tokens_consumed: 540,
        response_status: "error",
        processing_time_ms: 1820,
        request_params: null,
        created_at: "2026-04-02T11:00:00Z",
      },
    ],
    total: 2,
    page: 1,
    limit: 10,
    has_more: true,
    ...overrides,
  };
}

beforeEach(() => {
  useUserStore.getState().reset();
  useSettingsStore.getState().reset();
  getHistoryMock.mockReset();
  getHistoryMock.mockResolvedValue(page());
});

describe("HistoryPage", () => {
  it("renders the loaded items with localized service labels", async () => {
    render(<HistoryPage />);
    await waitFor(() => expect(getHistoryMock).toHaveBeenCalled());
    const list = await screen.findByTestId("history-list");
    expect(list).toBeInTheDocument();
    expect(within(list).getByText("Text")).toBeInTheDocument();
    expect(within(list).getByText("Image")).toBeInTheDocument();
    expect(within(list).getByText("120 tokens")).toBeInTheDocument();
  });

  it("applies the selected service filter and resets to page 1", async () => {
    render(<HistoryPage />);
    await waitFor(() => expect(getHistoryMock).toHaveBeenCalledTimes(1));

    await userEvent.selectOptions(screen.getByLabelText("Filter by service"), "image");

    await waitFor(() =>
      expect(getHistoryMock).toHaveBeenLastCalledWith({
        page: 1,
        limit: 10,
        service_type: "image",
      }),
    );
  });

  it("advances the page when Next is clicked", async () => {
    render(<HistoryPage />);
    await waitFor(() => expect(getHistoryMock).toHaveBeenCalledTimes(1));

    await userEvent.click(screen.getByRole("button", { name: "Next" }));
    await waitFor(() => expect(getHistoryMock).toHaveBeenLastCalledWith({ page: 2, limit: 10 }));
  });

  it("disables Next when there are no more pages", async () => {
    getHistoryMock.mockResolvedValueOnce(page({ has_more: false }));
    render(<HistoryPage />);
    await waitFor(() => expect(getHistoryMock).toHaveBeenCalled());
    const nextBtn = await screen.findByRole("button", { name: "Next" });
    await waitFor(() => expect(nextBtn).toBeDisabled());
  });

  it("renders an error state with retry when the API fails", async () => {
    getHistoryMock.mockRejectedValueOnce(new Error("boom"));
    render(<HistoryPage />);
    const retry = await screen.findByRole("button", { name: "Retry" });
    expect(retry).toBeInTheDocument();

    getHistoryMock.mockResolvedValueOnce(page({ items: [], has_more: false }));
    await userEvent.click(retry);
    expect(await screen.findByTestId("history-empty")).toBeInTheDocument();
  });
});
