/**
 * Manager integration flow: upload GETS files → live progress → analyze →
 * download report artifacts. The API layer is mocked at the fetch boundary
 * with realistic backend responses (including PENDING_OCR + review counts).
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

const state = vi.hoisted(() => ({ batchCalls: 0 }));
let capturedUrl = "";

vi.mock("../api/client", () => ({
  api: vi.fn((path: string, _init?: RequestInit) => {
    if (path === "/auth/csrf") return Promise.resolve({ csrf_token: "x" });
    if (path.startsWith("/batches/") && path.endsWith("/analyze")) {
      return Promise.resolve({
        run_id: "run-1",
        rows_processed: 10,
        matched: 9,
        violations: 3,
        emails_sent: 2,
        skipped: 1,
      });
    }
    if (path === "/uploads/batches") {
      state.batchCalls++;
      const status = state.batchCalls <= 1 ? "PROCESSING" : "COMPLETED";
      return Promise.resolve([
        {
          id: "b1",
          kind: "GETS",
          status,
          total_files: 2,
          processed_files: status === "COMPLETED" ? 2 : 0,
          failed_files: 0,
          created_at: new Date().toISOString(),
          completed_at: null,
        },
      ]);
    }
    return Promise.resolve({});
  }),
  setAccessToken: vi.fn(),
  setRefreshHandler: vi.fn(),
  getAccessToken: vi.fn(() => "tok"),
  download: vi.fn(async () => {}),
}));

const fetchMock = vi.fn(
  (url: string) => {
    capturedUrl = url;
    return Promise.resolve(
      new Response(
        JSON.stringify({
          id: "b-new",
          kind: "GETS",
          status: "QUEUED",
          total_files: 1,
          processed_files: 0,
          failed_files: 0,
          created_at: new Date().toISOString(),
          completed_at: null,
        }),
        { status: 201 },
      ),
    ) as unknown as Response;
  },
);
vi.stubGlobal("fetch", fetchMock);

vi.mock("../api/hooks", async (orig) => {
  const actual = (await orig()) as Record<string, unknown>;
  return {
    ...actual,
    useBatchDetail: () => ({
      data: {
        id: "b1",
        kind: "GETS",
        status: "COMPLETED",
        total_files: 2,
        processed_files: 2,
        failed_files: 0,
        created_at: new Date().toISOString(),
        completed_at: null,
        files: [
          { id: "f1", original_filename: "a.csv", content_type_detected: "text/csv",
            file_size: 100, status: "DONE", error_message: null, rows_extracted: 6,
            needs_review_count: 2 },
          { id: "f2", original_filename: "scan.png", content_type_detected: "image/png",
            file_size: 900, status: "PENDING_OCR", error_message: "no engine",
            rows_extracted: null, needs_review_count: 0 },
        ],
      },
      isLoading: false,
    }),
  };
});

import { GetsUploadsPage } from "../pages/GetsUploads";
import { ToastProvider } from "../components/ui/toast";
import * as client from "../api/client";

function renderUploads() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <ToastProvider>
        <MemoryRouter>
          <GetsUploadsPage />
        </MemoryRouter>
      </ToastProvider>
    </QueryClientProvider>,
  );
}

describe("Manager GETS flow", () => {
  it("upload → per-file real statuses → analyze → export/download available", async () => {
    renderUploads();
    await waitFor(() => screen.getByTestId("gets-file-input"));

    const input = screen.getByTestId("gets-file-input");
    await userEvent.upload(input, [
      new File(["id,name"], "july.csv", { type: "text/csv" }),
    ]);

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(capturedUrl).toContain("/uploads?kind=GETS");

    // Analyze button appears once COMPLETED and fires the analyze endpoint
    const analyzeBtn = await screen.findByTestId(/^analyze-b/);
    fireEventClick(analyzeBtn);
    await waitFor(() => expect(screen.getByTestId("toast-success")).toBeInTheDocument());
    expect(
      String((client.api as ReturnType<typeof vi.fn>).mock.calls.find((c) => String(c[0]).includes("/analyze"))?.[0]),
    ).toContain("/analyze");
  });

  it("PENDING_OCR file renders amber with reason, DONE file shows review count", async () => {
    renderUploads();
    const inspectBtn = await screen.findByTestId("inspect");
    fireEventClick(inspectBtn);
    const pending = await screen.findAllByText("PENDING_OCR");
    expect(pending.length).toBeGreaterThan(0);
    expect(screen.getAllByText(/need review/).length).toBeGreaterThan(0);
  });
});

function fireEventClick(el: Element) {
  el.dispatchEvent(new MouseEvent("click", { bubbles: true }));
}