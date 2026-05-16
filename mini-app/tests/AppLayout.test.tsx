import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";

import { AppLayout } from "@/layouts/AppLayout";
import { HomePage } from "@/pages/HomePage";
import { BalancePage } from "@/pages/BalancePage";

function renderAt(path: string) {
  const router = createMemoryRouter(
    [
      {
        path: "/",
        element: <AppLayout />,
        children: [
          { index: true, element: <HomePage /> },
          { path: "balance", element: <BalancePage /> },
        ],
      },
    ],
    { initialEntries: [path] },
  );
  return render(<RouterProvider router={router} />);
}

describe("AppLayout", () => {
  it("renders home content at /", () => {
    renderAt("/");
    expect(screen.getByText("Welcome")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Telegram AI Agent" })).toBeInTheDocument();
  });

  it("renders balance page at /balance", () => {
    renderAt("/balance");
    expect(screen.getByText("Token balance")).toBeInTheDocument();
    expect(screen.getByTestId("balance")).toHaveTextContent("—");
  });

  it("exposes the active colour scheme", () => {
    renderAt("/");
    expect(screen.getByTestId("active-scheme")).toBeInTheDocument();
  });
});
