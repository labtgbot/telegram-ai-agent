import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { DashboardScreen } from "@/components/dashboard/dashboard-screen";
import { buildDashboardSnapshot } from "@/lib/dashboard/mock";
import type { DashboardSnapshot } from "@/lib/dashboard/types";

const ANCHOR = new Date("2025-05-15T12:00:00.000Z");

function snapshotResponse(snapshot: DashboardSnapshot): Response {
  return new Response(JSON.stringify(snapshot), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

describe("<DashboardScreen />", () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.setSystemTime(ANCHOR);
  });

  afterEach(() => {
    vi.useRealTimers();
    cleanup();
    vi.restoreAllMocks();
  });

  it("renders the initial snapshot's KPI cards", () => {
    const initial = buildDashboardSnapshot("7d", { now: ANCHOR });
    render(<DashboardScreen initialSnapshot={initial} />);
    expect(screen.getByRole("heading", { name: /dashboard/i })).toBeInTheDocument();
    expect(screen.getByLabelText(/Users total KPI/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/MRR KPI/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/Tokens sold KPI/i)).toBeInTheDocument();
  });

  it("re-fetches when the period selector changes", async () => {
    const initial = buildDashboardSnapshot("7d", { now: ANCHOR });
    const next = buildDashboardSnapshot("30d", { now: ANCHOR });
    const fetchMock = vi.fn().mockResolvedValue(snapshotResponse(next));
    vi.stubGlobal("fetch", fetchMock);

    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime.bind(vi) });
    render(<DashboardScreen initialSnapshot={initial} />);

    const tab = screen.getByRole("tab", { name: "30d" });
    await user.click(tab);

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/admin/dashboard?period=30d",
      expect.objectContaining({ cache: "no-store" }),
    );
  });

  it("polls again after the configured interval", async () => {
    const initial = buildDashboardSnapshot("7d", { now: ANCHOR });
    const fetchMock = vi.fn().mockResolvedValue(snapshotResponse(initial));
    vi.stubGlobal("fetch", fetchMock);

    render(<DashboardScreen initialSnapshot={initial} refreshIntervalMs={1_000} />);

    expect(fetchMock).not.toHaveBeenCalled();
    await act(async () => {
      vi.advanceTimersByTime(1_050);
    });
    expect(fetchMock).toHaveBeenCalledTimes(1);

    await act(async () => {
      vi.advanceTimersByTime(1_050);
    });
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("surfaces an error state without losing the previous snapshot", async () => {
    const initial = buildDashboardSnapshot("7d", { now: ANCHOR });
    const fetchMock = vi.fn().mockRejectedValue(new Error("boom"));
    vi.stubGlobal("fetch", fetchMock);

    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime.bind(vi) });
    render(<DashboardScreen initialSnapshot={initial} />);

    await user.click(screen.getByRole("button", { name: /refresh/i }));

    expect(await screen.findByText(/refresh failed/i)).toBeInTheDocument();
    // KPI cards still rendered from the prior snapshot.
    expect(screen.getByLabelText(/Users total KPI/i)).toBeInTheDocument();
    consoleSpy.mockRestore();
  });
});
