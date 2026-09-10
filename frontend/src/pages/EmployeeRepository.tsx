import { useEffect, useMemo, useRef, useState, type ChangeEvent } from "react";
import { Link } from "react-router-dom";
import { AgGridReact } from "ag-grid-react";
import type { ColDef } from "ag-grid-community";
import { ModuleRegistry, AllCommunityModule } from "ag-grid-community";
import "ag-grid-community/styles/ag-grid.css";
import "ag-grid-community/styles/ag-theme-quartz.css";

ModuleRegistry.registerModules([AllCommunityModule]);

import { errorMessage, useEmployees, useEmployeeCorrection } from "../api/hooks";
import { useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { type Employee } from "../api/endpoints";
import {
  Button,
  Card,
  EmptyState,
  PageHeader,
  ReviewBadge,
  Skeleton,
} from "../components/ui/kit";
import { useToast } from "../components/ui/toast";

type Props = { readOnly?: boolean; title?: string; subtitle?: string };

/** Employee-repository upload (CSV/XLSX/scan). The batch processes inline;
 * the grid refreshes from parsed rows. */
function RepoUpload() {
  const inputRef = useRef<HTMLInputElement>(null);
  const qc = useQueryClient();
  const toast = useToast();
  const [busy, setBusy] = useState(false);

  const onFiles = async (e: ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files ?? []);
    e.target.value = "";
    if (!files.length) return;
    setBusy(true);
    try {
      const form = new FormData();
      files.forEach((f) => form.append("files", f));
      await api("/uploads?kind=EMPLOYEE_REPO", { method: "POST", body: form });
      toast("success", `Uploaded ${files.length} file(s) — repository updating`);
      qc.invalidateQueries({ queryKey: ["employees"] });
    } catch (err) {
      toast("error", errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <input
        ref={inputRef}
        type="file"
        accept=".csv,.xlsx,.xls,.pdf,.png,.jpg,.jpeg"
        multiple
        hidden
        data-testid="repo-upload-input"
        onChange={onFiles}
      />
      <Button onClick={() => inputRef.current?.click()} disabled={busy} data-testid="upload-repo">
        {busy ? "Uploading…" : "Upload repository"}
      </Button>
    </>
  );
}

export function EmployeeRepositoryPage({ readOnly = false, title = "Employee Repository", subtitle }: Props) {
  const { data, isLoading } = useEmployees();
  const gridRef = useRef<AgGridReact<Employee>>(null);
  const toast = useToast();
  const [tab, setTab] = useState<"all" | "review">("all");

  const correct = useEmployeeCorrection();
  useEffect(() => {
    if (correct.isSuccess) toast("success", "Correction saved — review flag cleared");
    if (correct.isError) toast("error", errorMessage(correct.error));
  }, [correct.isSuccess, correct.isError, correct.error, toast]);

  const rows = useMemo(() => {
    const items = data?.items ?? [];
    return tab === "review" ? items.filter((e) => e.needs_review) : items;
  }, [data, tab]);

  const flaggedCount = (data?.items ?? []).filter((e) => e.needs_review).length;

  // AG Grid inline editing: click a cell on a flagged row, edit, Enter —
  // PATCH fires, new version created server-side, flag clears. One click away
  // directly on the row (locked requirement 3a).
  const columnDefs = useMemo<ColDef<Employee>[]>(
    () => [
      {
        headerName: "Review",
        width: 150,
        pinned: "left",
        cellClassRules: {
          "bg-warning-100/60": (p) => !!p.data?.needs_review,
        },
        cellRenderer: (p: { data?: Employee }) =>
          p.data?.needs_review ? <ReviewBadge note={p.data.review_note} /> : "",
      },
      {
        field: "employee_code",
        headerName: "Employee ID",
        editable: !readOnly,
        cellRenderer: readOnly
          ? undefined
          : (p: { data?: Employee; value?: string }) =>
              p.data ? (
                <Link
                  to={`/employees/${p.data.id}`}
                  className="text-primary-600 hover:underline"
                >
                  {p.value}
                </Link>
              ) : (
                p.value
              ),
      },
      { field: "full_name", headerName: "Full Name", editable: !readOnly, flex: 1 },
      { field: "official_email", headerName: "Official Email", editable: !readOnly, flex: 1 },
      { field: "personal_email", headerName: "Personal Email", editable: !readOnly, flex: 1 },
      { field: "department", headerName: "Department", editable: !readOnly },
      {
        headerName: "OCR Confidence",
        width: 130,
        valueGetter: (p) =>
          p.data?.ocr_confidence != null
            ? `${Math.round(p.data.ocr_confidence * 100)}%`
            : "—",
      },
    ],
    [readOnly],
  );

  const onCellValueChanged = (e: { data: Employee; colDef: { field?: string }; oldValue?: string }) => {
    const field = e.colDef.field;
    if (!field || e.oldValue === e.data[field as keyof Employee]) return;
    correct.mutate({ id: e.data.id, field, value: String(e.data[field as keyof Employee] ?? "") });
  };

  if (isLoading) return <Skeleton rows={8} />;

  return (
    <div>
      <PageHeader
        title={title}
        subtitle={
          subtitle ??
          `Inline correction: double-click a cell on a flagged row to fix it — saving clears the flag.`
        }
        actions={
          <div className="flex items-center gap-2">
            {!readOnly && <RepoUpload />}
            <div className="flex gap-2" role="tablist">
            <Button
              variant={tab === "all" ? "primary" : "secondary"}
              onClick={() => setTab("all")}
              role="tab"
            >
              All employees
            </Button>
            <Button
              variant={tab === "review" ? "primary" : "secondary"}
              onClick={() => setTab("review")}
              role="tab"
              className={tab !== "review" && flaggedCount > 0 ? "!border-warning-700/40 !text-warning-700" : ""}
              data-testid="tab-needs-review"
            >
              Needs review{flaggedCount > 0 ? ` (${flaggedCount})` : ""}
            </Button>
            </div>
          </div>
        }
      />

      {rows.length === 0 ? (
        <Card>
          <EmptyState
            title={tab === "review" ? "Nothing awaiting review" : "No employees uploaded yet"}
            hint={tab === "review" ? "Flagged rows will appear here after OCR processing." : "Upload an employee repository CSV/XLSX to get started."}
          />
        </Card>
      ) : (
        <Card className="overflow-hidden">
          <div
            className="ag-theme-quartz h-[62vh] w-full"
            data-testid="employees-grid"
          >
            <AgGridReact
              ref={gridRef}
              rowData={rows}
              columnDefs={columnDefs}
              pagination
              paginationPageSize={50}
              defaultColDef={{
                sortable: true,
                filter: true,
                resizable: true,
                suppressMovable: true,
              }}
              getRowStyle={(p) =>
                p.data?.needs_review
                  ? { background: "var(--color-warning-100)" }
                  : undefined
              }
              onCellValueChanged={readOnly ? undefined : onCellValueChanged}
              quickFilterText={undefined}
              rowClassRules={{
                "[&_td]:bg-warning-100": (_p) => false,
              }}
            />
          </div>
        </Card>
      )}
      {!readOnly && (
        <p className="mt-3 text-xs text-gray-400">
          Edits create a new immutable version — full history is preserved per employee.
        </p>
      )}
    </div>
  );
}
