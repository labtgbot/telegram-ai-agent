import type { ComponentType, ReactElement } from "react";
import { lazy } from "react";
import { render, screen } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const sentryMock = vi.hoisted(() => ({
  captureException: vi.fn(),
}));

vi.mock("@/lib/sentry", () => ({
  Sentry: sentryMock,
}));

function Page({ label }: { label: string }): ReactElement {
  return <div>{label}</div>;
}

function pageComponent(label: string): ComponentType {
  return function TestPage(): ReactElement {
    return <Page label={label} />;
  };
}

async function renderAppWithFailingChild(error: Error): Promise<void> {
  vi.resetModules();
  vi.doMock("@/hooks/useTelegram", () => ({
    useTelegramBootstrap: vi.fn(),
  }));
  vi.doMock("@/router", () => ({
    router: createMemoryRouter([{ path: "/", element: <Page label="router ready" /> }]),
  }));
  vi.doMock("@/components/ConsentBanner", () => ({
    ConsentBanner: () => {
      throw error;
    },
  }));

  const { App } = await import("@/App");
  render(<App />);
}

async function renderRouterWithFailingRoute(component: ComponentType): Promise<void> {
  vi.resetModules();
  window.history.pushState({}, "", "/home");
  vi.doMock("@/routePages", () => ({
    HomePage: component,
    BalancePage: pageComponent("balance"),
    HistoryPage: pageComponent("history"),
    NotFoundPage: pageComponent("not found"),
    ProfilePage: pageComponent("profile"),
    ReferralPage: pageComponent("referral"),
    SettingsPage: pageComponent("settings"),
  }));

  const { router } = await import("@/router");
  render(<RouterProvider router={router} />);
}

describe("error recovery", () => {
  let consoleErrorMock: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    sentryMock.captureException.mockReset();
    consoleErrorMock = vi.spyOn(console, "error").mockImplementation(() => undefined);
  });

  afterEach(() => {
    consoleErrorMock.mockRestore();
    vi.doUnmock("@/hooks/useTelegram");
    vi.doUnmock("@/router");
    vi.doUnmock("@/components/ConsentBanner");
    vi.doUnmock("@/routePages");
    vi.resetModules();
  });

  it("shows a reloadable app fallback when a child render crashes", async () => {
    const failure = new Error("app render failed");

    await renderAppWithFailingChild(failure);

    const fallback = await screen.findByRole("alert");
    expect(fallback).toHaveTextContent("Something went wrong");
    expect(fallback).toHaveTextContent("Reload the Mini App and try again.");
    expect(screen.getByRole("button", { name: "Reload app" })).toBeInTheDocument();
    expect(sentryMock.captureException).toHaveBeenCalledWith(failure);
  });

  it("shows a reloadable route fallback when a lazy chunk fails", async () => {
    const failure = new Error("Loading chunk failed");
    const BrokenHomePage = lazy(() => Promise.reject(failure));

    await renderRouterWithFailingRoute(BrokenHomePage);

    const fallback = await screen.findByRole("alert");
    expect(fallback).toHaveTextContent("Could not load this screen");
    expect(fallback).toHaveTextContent("Reload the Mini App to fetch the screen again.");
    expect(screen.getByRole("button", { name: "Reload app" })).toBeInTheDocument();
    expect(sentryMock.captureException).toHaveBeenCalledWith(failure);
  });
});
