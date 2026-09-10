/** Analytics page: renders sectioned charts from the aggregation payload,
 *  empty state with no data, and HR route denial. */
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import type { ReactNode } from "react";

type Role = "MASTER_ADMIN" | "EXECUTIVE" | "MANAGER" | "HR";

const mockAuth = vi.hoisted(() => ({
  user: null as null | { id: string; email: string; role: Role },
  loading: false,
}));

let payload: Record<string, unknown> = {};

vi.mock("../auth/AuthContext", () => ({
  AuthProvider: ({ children }: { children: ReactNode }) => <>{children}</>,
  useAuth: () => ({
    user: mockAuth.user,
    loading: mockAuth.loading,
    login: vi.fn(),
    logout: vi.fn(),
  }),
}));

vi.mock("../api/client", () => ({
  api: vi.fn(async (path: string) => {
    if (path === "/analytics/summary") return payload;
    return {};
  }),
  setAccessToken: vi.fn(),
  setRefreshHandler: vi.fn(),
  getAccessToken: vi.fn(() => null),
  download: vi.fn(),
}));

import { AppRoutes } from "../App";
import { ToastProvider } from "../components/ui/toast";

function renderAt(path: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <ToastProvider>
        <MemoryRouter initialEntries={[path]}>
          <AppRoutes />
        </MemoryRouter>
      </ToastProvider>
    </QueryClientProvider>,
  );
}

describe("analytics page", () => {
  it("renders all sections + by-manager table for MASTER_ADMIN", async () => {
    payload = {
      scoped_to_self: false,
      monthly: [
        { month: "2026-05", violations: 4, rows_processed: 20, matched: 16, batches: 2, files_processed: 3 },
      ],
      emails: { sent: 3, missing: 1, errored: 0, skipped: 0 },
      by_manager: [
        { manager_id: "m1", manager_name: "Ann Manager", manager_email: "a@x.io", violations: 4, runs: 2, batches: 2 },
      ],
    };
    mockAuth.user = { id: "ma", email: "ma@x.io", role: "MASTER_ADMIN" };
    renderAt("/analytics");
    expect(await screen.findByTestId("analytics-page")).toBeInTheDocument();
    expect(screen.getByText("Violations over time")).toBeInTheDocument();
    expect(screen.getByText("Processed vs matched")).toBeInTheDocument();
    expect(screen.getByText("Email outcomes")).toBeInTheDocument();
    expect(screen.getByText("Upload volume")).toBeInTheDocument();
    expect(screen.getByTestId("by-manager-table")).toHaveTextContent("Ann Manager");
  });

  it("MANAGER sees scoped view without the by-manager table", async () => {
    payload = {
      scoped_to_self: true,
      monthly: [
        { month: "2026-05", violations: 1, rows_processed: 5, matched: 5, batches: 1, files_processed: 1 },
      ],
      emails: { sent: 0, missing: 0, errored: 0, skipped: 0 },
    };
    mockAuth.user = { id: "m1", email: "m@x.io", role: "MANAGER" };
    renderAt("/analytics");
    expect(await screen.findByTestId("analytics-page")).toBeInTheDocument();
    expect(screen.getByText("Your workspace only.")).toBeInTheDocument();
    expect(screen.queryByTestId("by-manager-table")).not.toBeInTheDocument();
  });

  it("shows the empty state when there is no data", async () => {
    payload = { scoped_to_self: true, monthly: [], emails: { sent: 0, missing: 0, errored: 0, skipped: 0 } };
    mockAuth.user = { id: "m2", email: "m2@x.io", role: "MANAGER" };
    renderAt("/analytics");
    expect(await screen.findByTestId("analytics-page")).toBeInTheDocument();
    expect(await screen.findByText("No analytics yet")).toBeInTheDocument();
  });

  it("HR sees their manager's scoped analytics view", async () => {
    payload = {
      scoped_to_self: true,
      monthly: [
        { month: "2026-05", violations: 2, rows_processed: 8, matched: 8, batches: 1, files_processed: 1 },
      ],
      emails: { sent: 0, missing: 0, errored: 0, skipped: 0 },
    };
    mockAuth.user = { id: "h1", email: "h@x.io", role: "HR" };
    renderAt("/analytics");
    expect(await screen.findByTestId("analytics-page")).toBeInTheDocument();
    expect(screen.getByText("Your manager's workspace.")).toBeInTheDocument();
    expect(screen.queryByTestId("by-manager-table")).not.toBeInTheDocument();
  });
});
