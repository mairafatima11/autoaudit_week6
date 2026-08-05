import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import { renderWithProviders } from "./test-utils";
import { Dashboard } from "../pages/Dashboard";

describe("Dashboard page", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => [],
      })
    );
  });

  it("shows the empty state when there are no runs and no active run", async () => {
    renderWithProviders(<Dashboard />);
    await waitFor(() => expect(screen.getByText("No audits yet")).toBeInTheDocument());
  });

  it("shows the repo source input and Run Audit button", () => {
    renderWithProviders(<Dashboard />);
    expect(screen.getByPlaceholderText("repo path or git URL")).toBeInTheDocument();
    expect(screen.getByText("Run Audit")).toBeInTheDocument();
  });
});
