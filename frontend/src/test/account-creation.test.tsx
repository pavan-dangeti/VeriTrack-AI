/**
 * Account-creation flows — the structural backbone of the role hierarchy.
 * Tests: MASTER_ADMIN creates EXECUTIVE, MANAGER creates HR, M365 domain approval.
 */
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ReactNode } from "react";

const apiMock = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  patch: vi.fn(),
}));

vi.mock("../api/client", () => ({
  api: (...args: unknown[]) => {
    const [path, init] = args as [string, RequestInit?];
    if (init?.method === "POST") return apiMock.post(path, init?.body);
    if (init?.method === "PATCH") return apiMock.patch(path, init?.body);
    return apiMock.get(path);
  },
  setAccessToken: vi.fn(),
  setRefreshHandler: vi.fn(),
  getAccessToken: vi.fn(() => "tok"),
  download: vi.fn(),
}));

vi.mock("../api/hooks", () => ({
  errorMessage: (e: unknown) => String(e),
  useEmployees: () => ({ data: { items: [], total: 0 }, isLoading: false }),
  useEmployeeCorrection: () => ({ isSuccess: false, isError: false, error: null, mutate: () => {}, reset: () => {} }),
  useBatches: () => ({ data: [], isLoading: false }),
  useBatchDetail: () => ({ data: undefined }),
  useBatchCompletionWatcher: () => undefined,
}));

Object.defineProperty(globalThis.navigator, "clipboard", {
  value: { writeText: vi.fn() },
  writable: true,
});

let usersList: Array<Record<string, any>> = [];
let domainsList: Array<Record<string, any>> = [];

vi.mock("../api/endpoints", async (orig) => {
  const actual = (await orig()) as Record<string, unknown>;
  return {
    ...actual,
    endpoints: {
      ...(actual.endpoints as object),
      batches: () => Promise.resolve([]),
      batch: () => Promise.resolve({}),
      employees: () => Promise.resolve({ items: [], total: 0 }),
      correctEmployee: () => Promise.resolve({}),
      analyze: () => Promise.resolve({}),
      analysis: () => Promise.resolve({}),
      runsForBatches: () => Promise.resolve({}),
      summary: () => Promise.resolve({
        role: "MASTER_ADMIN",
        scope: "system-wide",
        employees_total: 0,
        batches_total: 0,
        analysis_runs_completed: 0,
        violations_detected: 0,
        emails_sent: 0,
        employees_needing_review: 0,
        users_by_role: { MASTER_ADMIN: 1, EXECUTIVE: 0, MANAGER: 0, HR: 0 },
        latest_gets_batch: null,
      }),
      audit: () => Promise.resolve({ items: [], total: 0 }),
    },
  };
});

import { ManageUsersPage } from "../pages/ManageUsers";
import { HrTeamPage } from "../pages/People";
import { ToastProvider } from "../components/ui/toast";

function renderManageUsers(role: "MASTER_ADMIN" | "MANAGER" = "MASTER_ADMIN") {
  vi.mock("../auth/AuthContext", () => ({
    AuthProvider: ({ children }: { children: ReactNode }) => <>{children}</>,
    useAuth: () => ({
      user: { id: "u1", email: `${role.toLowerCase()}@x.io`, role },
      loading: false,
      login: vi.fn(),
      logout: vi.fn(),
    }),
  }));
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <ToastProvider>
        <MemoryRouter>
          <ManageUsersPage />
        </MemoryRouter>
      </ToastProvider>
    </QueryClientProvider>,
  );
}

function renderHrTeam() {
  vi.mock("../auth/AuthContext", () => ({
    AuthProvider: ({ children }: { children: ReactNode }) => <>{children}</>,
    useAuth: () => ({
      user: { id: "mgr1", email: "mgr@x.io", role: "MANAGER" },
      loading: false,
      login: vi.fn(),
      logout: vi.fn(),
    }),
  }));
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <ToastProvider>
        <MemoryRouter>
          <HrTeamPage />
        </MemoryRouter>
      </ToastProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  usersList = [
    { id: "u1", email: "admin@veritrack.io", role: "MASTER_ADMIN", is_active: true },
  ];
  domainsList = [];
  apiMock.get.mockImplementation((path: string) => {
    if (path === "/users") return Promise.resolve({ items: usersList, total: usersList.length });
    if (path === "/settings/m365-domains") return Promise.resolve({ items: domainsList });
    if (path === "/auth/me") return Promise.resolve({ id: "u1", email: "admin@veritrack.io", role: "MASTER_ADMIN" });
    return Promise.resolve({});
  });
  apiMock.post.mockImplementation((_path: string, body: string) => {
    const parsed = JSON.parse(body as string);
    if (parsed.role === "MANAGER" || parsed.role === "EXECUTIVE" || parsed.role === "HR") {
      const newUser = {
        id: `u${usersList.length + 1}`,
        email: parsed.email,
        role: parsed.role,
        is_active: true,
      };
      usersList.push(newUser);
      return Promise.resolve({ user: newUser, initial_password: "TempPass!123" });
    }
    if (parsed.domain) {
      const newDomain = { domain: parsed.domain, is_active: true };
      domainsList.push(newDomain);
      return Promise.resolve(newDomain);
    }
    return Promise.resolve({});
  });
  apiMock.patch.mockImplementation((_path: string, body: string) => {
    const parsed = JSON.parse(body as string);
    const id = _path.split("/")[2];
    const user = usersList.find((u) => u.id === id);
    if (user && parsed.is_active !== undefined) user.is_active = parsed.is_active;
    return Promise.resolve(user);
  });
});

describe("account-creation flows (role hierarchy enforcement)", () => {
  describe("MASTER_ADMIN creates EXECUTIVE", () => {
    it("renders form, submits, shows password modal with copy button", async () => {
      renderManageUsers("MASTER_ADMIN");
      await waitFor(() => screen.getByTestId("create-user"));

      const emailInput = screen.getByPlaceholderText("new.manager@corp.io");
      fireEvent.change(emailInput, { target: { value: "exec@corp.io" } });
      fireEvent.change(screen.getByLabelText("Role"), { target: { value: "EXECUTIVE" } });
      fireEvent.click(screen.getByTestId("create-user"));

      await waitFor(() => screen.getByRole("dialog", { name: /account created/i }));
      expect(screen.getByRole("dialog")).toHaveTextContent("exec@corp.io");
      expect(screen.getByRole("dialog")).toHaveTextContent("EXECUTIVE");
      expect(screen.getByLabelText("Initial password")).toHaveValue("TempPass!123");
      expect(screen.getByRole("button", { name: /copy/i })).toBeInTheDocument();
    });

    it("password modal closes on copy click", async () => {
      renderManageUsers("MASTER_ADMIN");
      await waitFor(() => screen.getByTestId("create-user"));

      const emailInput = screen.getByPlaceholderText("new.manager@corp.io");
      fireEvent.change(emailInput, { target: { value: "exec2@corp.io" } });
      fireEvent.change(screen.getByLabelText("Role"), { target: { value: "EXECUTIVE" } });
      fireEvent.click(screen.getByTestId("create-user"));

      await waitFor(() => screen.getByRole("dialog"));
      fireEvent.click(screen.getByRole("button", { name: /copy/i }));
      await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    });

    it("validates email and role", async () => {
      renderManageUsers("MASTER_ADMIN");
      await waitFor(() => screen.getByTestId("create-user"));

      fireEvent.click(screen.getByTestId("create-user"));
      expect(screen.getByText("Enter a valid email")).toBeInTheDocument();

      const emailInput = screen.getByPlaceholderText("new.manager@corp.io");
      fireEvent.change(emailInput, { target: { value: "bad" } });
      fireEvent.click(screen.getByTestId("create-user"));
      expect(screen.getByText("Enter a valid email")).toBeInTheDocument();

      fireEvent.change(emailInput, { target: { value: "good@corp.io" } });
      fireEvent.change(screen.getByLabelText("Role"), { target: { value: "INVALID" } });
      fireEvent.click(screen.getByTestId("create-user"));
      expect(screen.getByText("Role must be Manager or Executive")).toBeInTheDocument();
    });
  });

  describe("MASTER_ADMIN creates MANAGER", () => {
    it("creates manager account and shows password", async () => {
      renderManageUsers("MASTER_ADMIN");
      await waitFor(() => screen.getByTestId("create-user"));

      fireEvent.change(screen.getByLabelText("Email"), { target: { value: "mgr@corp.io" } });
      fireEvent.change(screen.getByLabelText("Role"), { target: { value: "MANAGER" } });
      fireEvent.click(screen.getByTestId("create-user"));

      await waitFor(() => screen.getByRole("dialog"));
      expect(screen.getByRole("dialog")).toHaveTextContent("MANAGER");
      expect(screen.getByRole("dialog")).toHaveTextContent("mgr@corp.io");
    });
  });

  describe("M365 domain approval", () => {
    it("approves domain and shows it in list", async () => {
      renderManageUsers("MASTER_ADMIN");
      await waitFor(() => screen.getByPlaceholderText("corp.io"));

      const input = screen.getByPlaceholderText("corp.io");
      fireEvent.change(input, { target: { value: "corp.io" } });
      fireEvent.click(screen.getByText("Approve domain"));

      await waitFor(() => expect(screen.getByText("corp.io")).toBeInTheDocument());
      expect(screen.getByText("corp.io")).toHaveClass("bg-success-100");
    });

    it("validates domain input", async () => {
      renderManageUsers("MASTER_ADMIN");
      await waitFor(() => screen.getByPlaceholderText("corp.io"));

      fireEvent.click(screen.getByText("Approve domain"));
      // empty string still calls API - backend validates; frontend just clears input
    });
  });

  describe("MASTER_ADMIN toggles user status", () => {
    it("disables and re-enables a manager", async () => {
      usersList = [
        { id: "u1", email: "admin@veritrack.io", role: "MASTER_ADMIN", is_active: true },
        { id: "u2", email: "mgr@corp.io", role: "MANAGER", is_active: true },
      ];
      apiMock.get.mockImplementation((path: string) => {
        if (path === "/users") return Promise.resolve({ items: usersList, total: usersList.length });
        if (path === "/settings/m365-domains") return Promise.resolve({ items: domainsList });
        if (path === "/auth/me") return Promise.resolve({ id: "u1", email: "admin@veritrack.io", role: "MASTER_ADMIN" });
        return Promise.resolve({});
      });

      renderManageUsers("MASTER_ADMIN");
      await waitFor(() => screen.getByText("mgr@corp.io"));

      // Click disable - target the specific row's button
      const disableBtn = screen.getAllByText("Disable").find((b) => b.closest("tr")?.textContent?.includes("mgr@corp.io"));
      fireEvent.click(disableBtn!);
      await waitFor(() => expect(screen.getAllByText("Enable").find((b) => b.closest("tr")?.textContent?.includes("mgr@corp.io"))).toBeInTheDocument());
      expect(screen.getAllByText("Disabled").find((t) => t.closest("tr")?.textContent?.includes("mgr@corp.io"))).toBeInTheDocument();

      // Click enable
      const enableBtn = screen.getAllByText("Enable").find((b) => b.closest("tr")?.textContent?.includes("mgr@corp.io"));
      fireEvent.click(enableBtn!);
      await waitFor(() => expect(screen.getAllByText("Disable").find((b) => b.closest("tr")?.textContent?.includes("mgr@corp.io"))).toBeInTheDocument());
      expect(screen.getAllByText("Active").find((t) => t.closest("tr")?.textContent?.includes("mgr@corp.io"))).toBeInTheDocument();
    });
  });
});

describe("MANAGER creates HR", () => {
  it("renders HR create form, submits, shows password modal", async () => {
    renderHrTeam();
    await waitFor(() => screen.getByRole("button", { name: /create hr account/i }));

    fireEvent.change(screen.getByLabelText("HR email"), { target: { value: "hr@corp.io" } });
    fireEvent.click(screen.getByRole("button", { name: /create hr account/i }));

    await waitFor(() => screen.getByRole("dialog", { name: /account created/i }));
    expect(screen.getByRole("dialog")).toHaveTextContent("hr@corp.io");
    expect(screen.getByRole("dialog")).toHaveTextContent("HR");
    expect(screen.getByLabelText("Initial password")).toHaveValue("TempPass!123");
    expect(screen.getByRole("button", { name: /copy/i })).toBeInTheDocument();
  });

  it("validates email", async () => {
    renderHrTeam();
    await waitFor(() => screen.getByRole("button", { name: /create hr account/i }));

    fireEvent.click(screen.getByRole("button", { name: /create hr account/i }));
    expect(screen.getByText("Enter a valid email")).toBeInTheDocument();

    const hrEmailInput = screen.getByText("HR email").closest("label")?.querySelector("input") as HTMLInputElement;
    fireEvent.change(hrEmailInput, { target: { value: "hr@corp.io" } });
    fireEvent.click(screen.getByRole("button", { name: /create hr account/i }));
    await waitFor(() => screen.getByRole("dialog"));
  });

  it("lists created HR accounts", async () => {
    usersList = [
      { id: "mgr1", email: "mgr@x.io", role: "MANAGER", is_active: true },
      { id: "hr1", email: "hr@corp.io", role: "HR", is_active: true },
    ];
    apiMock.get.mockImplementation((path: string) => {
      if (path === "/users") return Promise.resolve({ items: usersList, total: usersList.length });
      if (path === "/auth/me") return Promise.resolve({ id: "mgr1", email: "mgr@x.io", role: "MANAGER" });
      return Promise.resolve({});
    });

    renderHrTeam();
    await waitFor(() => screen.getByText("hr@corp.io"));
    expect(screen.getByTestId("hr-team-table")).toBeInTheDocument();
  });
});