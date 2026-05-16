import { beforeEach, describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { ConsentBanner } from "@/components/ConsentBanner";
import { useConsentStore } from "@/store/useConsentStore";

describe("ConsentBanner", () => {
  beforeEach(() => {
    window.localStorage.clear();
    useConsentStore.getState().reset();
  });

  it("renders when no decision has been made", () => {
    render(<ConsentBanner />);
    expect(screen.getByTestId("consent-banner")).toBeInTheDocument();
    expect(screen.getByTestId("consent-accept")).toBeInTheDocument();
    expect(screen.getByTestId("consent-necessary")).toBeInTheDocument();
  });

  it("links to the Privacy Policy and Terms of Service", () => {
    render(<ConsentBanner />);
    const privacy = screen.getByRole("link", { name: /privacy policy/i });
    const terms = screen.getByRole("link", { name: /terms of service/i });
    expect(privacy).toHaveAttribute("href", "/privacy");
    expect(terms).toHaveAttribute("href", "/terms");
  });

  it("records 'accepted' and disappears when the user taps Accept all", async () => {
    render(<ConsentBanner />);
    await userEvent.click(screen.getByTestId("consent-accept"));
    expect(useConsentStore.getState().record?.decision).toBe("accepted");
    expect(screen.queryByTestId("consent-banner")).not.toBeInTheDocument();
  });

  it("records 'necessary' when the user taps Necessary only", async () => {
    render(<ConsentBanner />);
    await userEvent.click(screen.getByTestId("consent-necessary"));
    expect(useConsentStore.getState().record?.decision).toBe("necessary");
    expect(screen.queryByTestId("consent-banner")).not.toBeInTheDocument();
  });

  it("stays hidden when a current decision exists", () => {
    useConsentStore.getState().setDecision("accepted");
    render(<ConsentBanner />);
    expect(screen.queryByTestId("consent-banner")).not.toBeInTheDocument();
  });
});
