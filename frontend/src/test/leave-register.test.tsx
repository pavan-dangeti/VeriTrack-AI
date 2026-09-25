/** Company leave register: listing, manual entry, role-based controls. */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import type { ReactNode } from "react";

const state = vi.hoisted(() => ({
  role: "MANAGER" as string,
  calls: [] as { path: string; init?: RequestInit }[],
}));

vi.mock("../auth/AuthContext", () => ({
  AuthProvider: ({ children }: { children: ReactNode }) => <>{children}</>,
  useAuth: () => ({ user: { id: "u", email: "m@x.io", role: state.role }, loading: false }),
}));

vi.mock("../api/client", () => ({
  api: vi.fn((path: string, init?: RequestInit) => {
    state.calls.push({ path, init });
    if (path.startsWith("/leaves?")) {
      return Promise.resolve({
        total: 2,
        items: [
          { id: 1, employee_code: "100001", leave_date: "2026-07-17", leave_type: "Casual", source: "UPLOAD", batch_id: null, created_at: null },
          { id: 2, employee_code: "100004", leave_date: "2026-07-21", leave_type: null, source: "MANUAL", batch_id: null, created_at: null },
        ],
      });
    }
    if (path === "/leaves") return Promise.resolve({ inserted: 3 });
    return Promise.resolve({});
  }),
  upload: vi.fn(() => Promise.resolve({ id: "b", total_files: 1 })),
}));

import { LeaveRegisterPage } from "../pages/LeaveRegister";
import { ToastProvider } from "../components/ui/toast";

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <ToastProvider>
        <MemoryRouter>
          <LeaveRegisterPage />
        </MemoryRouter>
      </ToastProvider>
    </QueryClientProvider>,
  );
}

describe("LeaveRegisterPage", () => {
  it("lists entries with source badges and employee count", async () => {
    state.role = "MANAGER";
    renderPage();
    expect(await screen.findByTestId("leaves-table")).toBeInTheDocument();
    expect(screen.getByText("100001")).toBeInTheDocument();
    expect(screen.getByText("Imported")).toBeInTheDocument();
    expect(screen.getByText("Manual")).toBeInTheDocument();
    expect(screen.getByText("2 employee(s)")).toBeInTheDocument();
  });

  it("manager adds a leave range through the modal", async () => {
    state.role = "MANAGER";
    state.calls = [];
    renderPage();
    await userEvent.click(await screen.findByTestId("add-leave"));
    expect(screen.getByRole("dialog", { name: /add company leave/i })).toBeInTheDocument();
    await userEvent.type(screen.getByPlaceholderText("100001"), "100001");
    const dates = document.querySelectorAll<HTMLInputElement>("input[type=date]");
    await userEvent.type(dates[0], "2026-07-20");
    await userEvent.click(screen.getByTestId("save-leave"));
    await waitFor(() => expect(state.calls.some((c) => c.path === "/leaves" && c.init?.method === "POST")).toBe(true));
    const body = JSON.parse(String(state.calls.find((c) => c.path === "/leaves")!.init!.body));
    expect(body).toMatchObject({ employee_code: "100001", start_date: "2026-07-20" });
    expect(await screen.findByTestId("toast-success")).toHaveTextContent("3 leave day(s) added");
  });

  it("HR sees the register read-only", async () => {
    state.role = "HR";
    renderPage();
    expect(await screen.findByTestId("leaves-table")).toBeInTheDocument();
    expect(screen.queryByTestId("add-leave")).not.toBeInTheDocument();
    expect(screen.queryByTestId("leave-file-input")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /delete leave/i })).not.toBeInTheDocument();
  });
});
