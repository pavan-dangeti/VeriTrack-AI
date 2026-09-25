/** Sheet review: the reconstructed GETS grid, statuses and verification. */
import { render, screen, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

const cells = (hours: Record<number, number>, status = "USER_SIGNED") =>
  Array.from({ length: 31 }, (_, i) => ({
    day: i + 1,
    hours: hours[i + 1] ?? null,
    status: hours[i + 1] != null ? status : "EMPTY",
    raw: hours[i + 1] != null ? String(hours[i + 1]) : "",
    confidence: 0.99,
    corrected: i + 1 === 27,
  }));

const sheet = (verified: boolean) => ({
  employee_name: "DEMO USER, K (K.)",
  person_id: "100001",
  supplier: "ACME",
  job_family: "Engineer - Senior",
  month: 7,
  year: 2026,
  period: "2026-07",
  days_in_month: 31,
  weekdays: Array.from({ length: 31 }, (_, i) => ["We", "Th", "Fr", "Sa", "Su", "Mo", "Tu"][i % 7]),
  lines: [
    { row_index: 0, person_id: "100001", supplier: "ACME", job_family: "Eng", uom: "STD", project_id: "500001",
      sub_project: "Alpha", sub_project_id: "2000001", remarks: "Remark", cells: cells({ 1: 8, 2: 8 }),
      printed_total: 16, computed_total: 16, confidence: 0.99, issues: [], is_out_of_office: false },
    { row_index: 1, person_id: "100001", supplier: "ACME", job_family: "Eng", uom: "NC", project_id: "600001",
      sub_project: "Out Of Office", sub_project_id: "2100001", remarks: "Remark", cells: cells({ 17: 8, 27: 8 }, "PM_APPROVED"),
      printed_total: 16, computed_total: 16, confidence: 0.99, issues: [], is_out_of_office: true },
  ],
  totals: { NC: Array(31).fill(0), STD: Array(31).fill(0), TOTAL: Array(31).fill(0) },
  totals_printed_total: { NC: 16, STD: 16, TOTAL: 32 },
  checks: [
    { check: "row 1 (Alpha) sum", expected: 16, actual: 16, ok: true },
    { check: "NC day totals", expected: 31, actual: verified ? 31 : 29, ok: verified, mismatched_days: verified ? [] : [17, 27] },
  ],
  corrections: ["row 2 day 27 (NC day total 8): 3 → 8"],
  warnings: [],
  status: verified ? "CORRECTED" : "NEEDS_REVIEW",
  verified,
  confidence: 0.97,
});

const state = vi.hoisted(() => ({ verified: true }));

vi.mock("../api/client", () => ({
  api: vi.fn((path: string) => {
    if (path.endsWith("/extraction")) {
      return Promise.resolve({
        file: { id: "f1", original_filename: "gets_sample.png", status: "DONE", file_size: 1, content_type_detected: "image/png",
          error_message: null, rows_extracted: 2, needs_review_count: 0 },
        meta: { gets_sheets: [sheet(state.verified)] },
        rows: [],
      });
    }
    return Promise.resolve({});
  }),
  blobUrl: vi.fn(() => Promise.resolve("blob:x")),
}));

import { SheetReviewPage } from "../pages/SheetReview";

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/review/b1/f1"]}>
        <Routes>
          <Route path="/review/:batchId/:fileId" element={<SheetReviewPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("SheetReviewPage", () => {
  it("renders identity, the grid with GETS cell colours and the leave row", async () => {
    state.verified = true;
    renderPage();
    expect(await screen.findByTestId("sheet-review-page")).toBeInTheDocument();
    expect(screen.getByText("DEMO USER, K (K.)")).toBeInTheDocument();
    expect(screen.getByText("July 2026")).toBeInTheDocument();
    const grid = screen.getByTestId("timesheet-grid");
    expect(within(grid).getByText("Alpha")).toBeInTheDocument();
    expect(within(grid).getByText("Leave")).toBeInTheDocument();
    const signed = within(grid).getAllByText("8").filter((el) => el.className.includes("bg-gets-signed"));
    expect(signed).toHaveLength(2);
    expect(within(grid).getAllByText("8").some((el) => el.className.includes("ring-primary-500"))).toBe(true); // corrected
  });

  it("lists verification checks and automatic corrections", async () => {
    state.verified = true;
    renderPage();
    const checks = await screen.findByTestId("checks");
    expect(within(checks).getAllByLabelText("passed")).toHaveLength(2);
    expect(screen.getByText(/day 27/)).toBeInTheDocument();
    expect(screen.getByText("Auto-corrected")).toBeInTheDocument();
  });

  it("surfaces failed checks with the mismatching days", async () => {
    state.verified = false;
    renderPage();
    const checks = await screen.findByTestId("checks");
    expect(within(checks).getByLabelText("failed")).toBeInTheDocument();
    expect(within(checks).getByText(/days 17, 27/)).toBeInTheDocument();
    expect(screen.getByText("Needs review")).toBeInTheDocument();
  });
});
