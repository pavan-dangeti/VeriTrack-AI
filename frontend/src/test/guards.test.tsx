/**
 * Route protection: renders the router at specific paths per auth state —
 * the equivalent of typing URLs directly into the address bar. Hiding
 * sidebar links is cosmetic; these tests prove the ROUTES enforce roles.
 */
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import type { ReactNode } from "react";

export type Role = "MASTER_ADMIN" | "EXECUTIVE" | "MANAGER" | "HR";

const mockAuth = vi.hoisted(() => ({
  user: null as null | { id: string; email: string; role: Role },
  loading: false,
}));

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
  api: vi.fn().mockResolvedValue({}),
  setAccessToken: vi.fn(),
  setRefreshHandler: vi.fn(),
  getAccessToken: vi.fn(() => null),
  download: vi.fn(),
}));

import { AppRoutes } from "../App";
import { ToastProvider } from "../components/ui/toast";

function renderAt(path: string): ReturnType<typeof render> {
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

describe("route protection (direct-URL semantics)", () => {
  it("unauthenticated user typing /users is redirected to login", () => {
    mockAuth.user = null;
    renderAt("/users");
    expect(screen.queryByTestId("users-table")).not.toBeInTheDocument();
    expect(screen.queryByText("Manage Users")).not.toBeInTheDocument();
  });

  it("MANAGER typing /users lands on access-denied", () => {
    mockAuth.user = { id: "u1", email: "m@x.io", role: "MANAGER" };
    renderAt("/users");
    expect(screen.getByTestId("denied-path")).toBeInTheDocument();
    expect(screen.queryByTestId("users-table")).not.toBeInTheDocument();
  });

  it("HR typing /gets is denied", () => {
    mockAuth.user = { id: "u2", email: "h@x.io", role: "HR" };
    renderAt("/gets");
    expect(screen.getByTestId("denied-path")).toBeInTheDocument();
  });

  it("HR typing /employees is denied", () => {
    mockAuth.user = { id: "u2b", email: "h2@x.io", role: "HR" };
    renderAt("/employees");
    expect(screen.getByTestId("denied-path")).toBeInTheDocument();
  });

  it("EXECUTIVE typing /audit-logs is denied", () => {
    mockAuth.user = { id: "u3", email: "e@x.io", role: "EXECUTIVE" };
    renderAt("/audit-logs");
    expect(screen.getByTestId("denied-path")).toBeInTheDocument();
  });

  it("EXECUTIVE CAN open /all-reports (mirrored visibility)", () => {
    mockAuth.user = { id: "u5", email: "e5@x.io", role: "EXECUTIVE" };
    renderAt("/all-reports");
    expect(screen.getByText("All Reports")).toBeInTheDocument();
  });

  it("MASTER_ADMIN can open /users", async () => {
    mockAuth.user = { id: "u4", email: "a@x.io", role: "MASTER_ADMIN" };
    renderAt("/users");
    expect(await screen.findByTestId("create-user")).toBeInTheDocument();
  });
});
