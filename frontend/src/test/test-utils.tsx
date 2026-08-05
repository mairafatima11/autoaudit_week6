import type { ReactElement } from "react";
import { render } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { RunProvider } from "../lib/RunContext";

export function renderWithProviders(ui: ReactElement, { route = "/" } = {}) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  window.history.pushState({}, "", route);
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[route]}>
        <RunProvider>{ui}</RunProvider>
      </MemoryRouter>
    </QueryClientProvider>
  );
}
