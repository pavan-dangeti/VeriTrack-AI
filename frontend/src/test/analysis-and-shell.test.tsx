/** Analysis results, command palette, theme toggle and shared UI primitives. */
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import type { ReactNode } from "react";

vi.mock("../auth/AuthContext", () => ({
  AuthProvider: ({ children }: { children: ReactNode }) => <>{children}</>,
  useAuth: () => ({ user: { id: "u", email: "mgr@x.io", full_name: "Harish N", role: "MANAGER" }, loading: false, logout: vi.fn() }),
}));

vi.mock("../api/client", () => ({
  ApiError: class extends Error {},
  api: vi.fn((path: string) => {
    if (path.endsWith("/analysis")) {
      return Promise.resolve({
        run_id: "abcdef1234", batch_id: "b1", manager_id: "m", status: "COMPLETED",
        started_at: "2026-09-25T10:00:00Z", completed_at: "2026-09-25T10:00:05Z",
        totals: { files_processed: 4, rows_processed: 4, matched: 4, violations: 1, emails_sent: 1, emails_missing: 0, emails_errored: 0, skipped: 1 },
        violations: [{
          employee_code: "100003", employee_name: "Bravo Example", violation_reason: "x",
          email_to: "bravo.example@example.net", email_status: "SENT",
          details: { customer_leave_dates: ["2026-07-22", "2026-07-31"], missing_in_register: ["2026-07-31"] },
        }],
        skipped_rows: [{ employee_code: "999999", status: "NOT_IN_REPO", reason: "Employee ID not found" }],
      });
    }
    if (path.startsWith("/uploads/batches")) return Promise.resolve([]);
    return Promise.resolve({});
  }),
  download: vi.fn(),
}));

import { AnalysisResultsPage } from "../pages/AnalysisResults";
import { DashboardLayout } from "../layouts/DashboardLayout";
import { ToastProvider } from "../components/ui/toast";
import { StatusBadge, ProgressBar } from "../components/ui/kit";
import { fmtBytes, fmtHours, fmtPeriod } from "../lib/format";

function wrap(ui: ReactNode, path: string, route: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <ToastProvider>
        <MemoryRouter initialEntries={[path]}>
          <Routes>
            <Route path={route} element={ui} />
          </Routes>
        </MemoryRouter>
      </ToastProvider>
    </QueryClientProvider>,
  );
}

describe("AnalysisResultsPage", () => {
  it("shows totals, the missing register dates and skipped employees", async () => {
    wrap(<AnalysisResultsPage />, "/analysis/b1", "/analysis/:batchId");
    const table = await screen.findByTestId("violations-table");
    expect(within(table).getByText("Bravo Example")).toBeInTheDocument();
    expect(within(table).getAllByText(/31 Jul|Jul 31/)).toHaveLength(2); // in GETS + missing
    expect(within(table).getByText("bravo.example@example.net")).toBeInTheDocument();
    expect(screen.getByText("Not in your repository")).toBeInTheDocument();
    expect(screen.getByText("Run abcdef12", { exact: false })).toBeInTheDocument();
  });
});

describe("App shell", () => {
  it("command palette filters pages and navigates", async () => {
    wrap(<DashboardLayout />, "/dashboard", "/*");
    await userEvent.click(screen.getByTestId("open-palette"));
    const dialog = screen.getByRole("dialog", { name: /command palette/i });
    await userEvent.type(within(dialog).getByLabelText("Search pages"), "leave");
    const options = within(dialog).getAllByRole("option");
    expect(options).toHaveLength(1);
    expect(options[0]).toHaveTextContent("Company Leave Register");
    await userEvent.keyboard("{Enter}");
    expect(screen.queryByRole("dialog", { name: /command palette/i })).not.toBeInTheDocument();
  });

  it("Ctrl+K opens the palette and Escape closes it", async () => {
    wrap(<DashboardLayout />, "/dashboard", "/*");
    await userEvent.keyboard("{Control>}k{/Control}");
    expect(screen.getByRole("dialog", { name: /command palette/i })).toBeInTheDocument();
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("dialog", { name: /command palette/i })).not.toBeInTheDocument();
  });

  it("theme toggle switches the dark class", async () => {
    document.documentElement.classList.remove("dark");
    localStorage.setItem("vt-theme", "light");
    wrap(<DashboardLayout />, "/dashboard", "/*");
    await userEvent.click(screen.getByTestId("theme-toggle"));
    expect(document.documentElement.classList.contains("dark")).toBe(true);
    expect(localStorage.getItem("vt-theme")).toBe("dark");
    await userEvent.click(screen.getByTestId("theme-toggle"));
    expect(document.documentElement.classList.contains("dark")).toBe(false);
  });

  it("sidebar shows only the manager's sections and user initials", () => {
    wrap(<DashboardLayout />, "/dashboard", "/*");
    const sidebar = screen.getByTestId("sidebar");
    expect(within(sidebar).getByText("GETS Uploads")).toBeInTheDocument();
    expect(within(sidebar).queryByText("Manage Users")).not.toBeInTheDocument();
    expect(screen.getByText("HN")).toBeInTheDocument();
  });
});

describe("UI primitives", () => {
  it("status badges use friendly labels but keep the raw status", () => {
    render(<><StatusBadge status="PENDING_OCR" /><StatusBadge status="NEEDS_REVIEW" /><StatusBadge status="WEIRD" /></>);
    expect(screen.getByText("Awaiting OCR").closest("[data-status]")).toHaveAttribute("data-status", "PENDING_OCR");
    expect(screen.getByText("Needs review")).toBeInTheDocument();
    expect(screen.getByText("WEIRD")).toBeInTheDocument();
  });

  it("progress bar clamps and reports percent", () => {
    render(<ProgressBar value={7} max={4} />);
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "100");
  });

  it("format helpers", () => {
    expect(fmtBytes(512)).toBe("512 B");
    expect(fmtBytes(2048)).toBe("2 KB");
    expect(fmtBytes(3 * 1024 * 1024)).toBe("3.0 MB");
    expect(fmtHours(7.5)).toBe("7.5");
    expect(fmtHours(8)).toBe("8");
    expect(fmtPeriod("2026-07")).toMatch(/July 2026/);
    expect(fmtPeriod(null)).toBe("—");
  });
});
