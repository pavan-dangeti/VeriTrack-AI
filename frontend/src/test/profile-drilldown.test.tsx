/**
 * Profile pages + drill-down navigation: pages render role-scoped content,
 * rows link into profiles, and the route guard keeps users inside their role
 * (HR can't open /people/* or /employees/:id directly).
 */
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

const MANAGER_PROFILE = {
  id: "m1",
  email: "mgr@corp.io",
  role: "MANAGER",
  auth_type: "PASSWORD",
  is_active: true,
  manager_id: null,
  created_at: "2026-01-02T09:00:00Z",
  last_login_at: "2026-08-30T08:00:00Z",
  hr_accounts: [{ id: "h1", email: "hr@corp.io", is_active: true }],
  employee_count: 3,
  gets_batches_total: 2,
  gets_batches_completed: 1,
  gets_batches_recent: [
    { id: "b1", status: "COMPLETED", total_files: 4, failed_files: 0, created_at: "2026-07-01T10:00:00Z" },
  ],
};

const HR_PROFILE = {
  id: "h1",
  email: "hr@corp.io",
  role: "HR",
  auth_type: "PASSWORD",
  is_active: true,
  manager_id: "m1",
  created_at: "2026-02-02T09:00:00Z",
  last_login_at: "2026-08-29T08:00:00Z",
  manager: { id: "m1", email: "mgr@corp.io" },
};

const EMP_DETAIL = {
  id: "e1",
  manager_id: "m1",
  employee_code: "E-100",
  full_name: "Ann Weaver",
  official_email: "ann@corp.io",
  personal_email: null,
  department: "Ops",
  needs_review: false,
  review_note: null,
  ocr_confidence: 0.98,
  versions: [
    { version: 1, full_name: "Ann Weaver", official_email: "ann@corp.io", personal_email: null, department: "Ops", change_source: "UPLOAD", created_at: "2026-03-01T00:00:00Z" },
  ],
  gets_batches: [
    { id: "b1", status: "COMPLETED", total_files: 4, created_at: "2026-07-01T10:00:00Z" },
  ],
};

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
    if (path === "/users/m1/profile") return MANAGER_PROFILE;
    if (path === "/users/h1/profile") return HR_PROFILE;
    if (path === "/employees/e1/detail") return EMP_DETAIL;
    throw new Error(`unmocked api path: ${path}`);
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

const manager = { id: "m1", email: "mgr@corp.io", role: "MANAGER" as Role };

describe("profile pages", () => {
  it("MANAGER own /profile shows identity + role counters + HR list", async () => {
    mockAuth.user = manager;
    renderAt("/profile");
    expect(await screen.findByTestId("user-profile-page")).toBeInTheDocument();
    expect(screen.getAllByText("mgr@corp.io").length).toBeGreaterThan(0);
    expect(screen.getByText("HR accounts")).toBeInTheDocument();
    expect(screen.getByText("Employees in repository")).toBeInTheDocument();
    expect(screen.getByText("1 / 2")).toBeInTheDocument(); // GETS completed/total
    // HR list entry links to the drill-down profile
    const link = screen.getByRole("link", { name: "hr@corp.io" });
    expect(link).toHaveAttribute("href", "/people/h1");
  });

  it("MANAGER viewing HR profile via /people/:id sees manager link + back button", async () => {
    mockAuth.user = manager;
    renderAt("/people/h1");
    expect(await screen.findByTestId("user-profile-page")).toBeInTheDocument();
    expect(screen.getByText("Reports to")).toBeInTheDocument();
    const mgrLink = screen.getByRole("link", { name: "mgr@corp.io" });
    expect(mgrLink).toHaveAttribute("href", "/people/m1");
    expect(screen.getByTestId("back-button")).toBeInTheDocument();
  });

  it("HR own /profile shows 'Reports to' as plain text (no drill-up link)", async () => {
    mockAuth.user = { id: "h1", email: "hr@corp.io", role: "HR" };
    renderAt("/profile");
    expect(await screen.findByTestId("user-profile-page")).toBeInTheDocument();
    expect(screen.getByText("Reports to")).toBeInTheDocument();
    expect(screen.getByText("mgr@corp.io")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "mgr@corp.io" })).not.toBeInTheDocument();
  });

  it("MANAGER employee detail shows record, versions, and batches", async () => {
    mockAuth.user = manager;
    renderAt("/employees/e1");
    expect(await screen.findByTestId("employee-detail-page")).toBeInTheDocument();
    expect(screen.getAllByText("Ann Weaver").length).toBeGreaterThan(0);
    expect(screen.getAllByText("E-100").length).toBeGreaterThan(0);
    expect(screen.getByTestId("employee-versions-table")).toHaveTextContent("v1");
    expect(screen.getByTestId("employee-batches-table")).toHaveTextContent("COMPLETED");
    expect(screen.getByTestId("back-button")).toBeInTheDocument();
  });
});

describe("drill-down route protection", () => {
  it("HR typing /people/h1 directly is denied", () => {
    mockAuth.user = { id: "h1", email: "hr@corp.io", role: "HR" };
    renderAt("/people/h1");
    expect(screen.getByTestId("denied-path")).toBeInTheDocument();
    expect(screen.queryByTestId("user-profile-page")).not.toBeInTheDocument();
  });

  it("HR typing /employees/e1 directly is denied", () => {
    mockAuth.user = { id: "h1", email: "hr@corp.io", role: "HR" };
    renderAt("/employees/e1");
    expect(screen.getByTestId("denied-path")).toBeInTheDocument();
    expect(screen.queryByTestId("employee-detail-page")).not.toBeInTheDocument();
  });

  it("EXECUTIVE can drill into a manager profile", async () => {
    mockAuth.user = { id: "x1", email: "exec@corp.io", role: "EXECUTIVE" };
    renderAt("/people/m1");
    expect(await screen.findByTestId("user-profile-page")).toBeInTheDocument();
    expect(screen.getByText("GETS batch history")).toBeInTheDocument();
  });
});
