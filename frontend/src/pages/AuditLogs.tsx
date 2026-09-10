import { useMemo, useState } from "react";
import { AgGridReact } from "ag-grid-react";
import type { ColDef } from "ag-grid-community";
import { ModuleRegistry, AllCommunityModule } from "ag-grid-community";
import "ag-grid-community/styles/ag-grid.css";
import "ag-grid-community/styles/ag-theme-quartz.css";

ModuleRegistry.registerModules([AllCommunityModule]);

import { download } from "../api/client";
import { useApiQuery } from "../api/endpoints";
import { Button, Card, EmptyState, PageHeader, PageHeader as _PH, Skeleton, StatusBadge } from "../components/ui/kit";
import { useToast } from "../components/ui/toast";

interface AuditRow {
  id: number;
  timestamp: string;
  action: string;
  result: string;
  actor_user_id: string | null;
  target_entity: string | null;
  ip_address: string | null;
}

export function AuditLogsPage() {
  const [resultFilter, setResultFilter] = useState("");
  const { data, isLoading } = useApiQuery<{ items: AuditRow[]; total: number }>(
    ["audit", resultFilter],
    `/audit-logs?limit=200${resultFilter ? `&result=${resultFilter}` : ""}`,
  );
  const toast = useToast();

  const columnDefs = useMemo<ColDef<AuditRow>[]>(
    () => [
      { field: "id", width: 90 },
      {
        field: "timestamp",
        headerName: "Time",
        width: 180,
        valueFormatter: (p) => (p.value ? new Date(p.value).toLocaleString() : ""),
      },
      { field: "action", headerName: "Action", flex: 1 },
      {
        field: "result",
        headerName: "Result",
        width: 120,
        cellRenderer: (p: { value: string }) => <StatusBadge status={p.value} />,
      },
      { field: "actor_user_id", headerName: "Actor", width: 280 },
      { field: "target_entity", headerName: "Target", width: 140 },
      { field: "ip_address", headerName: "IP", width: 160 },
    ],
    [],
  );

  if (isLoading) return <Skeleton rows={8} />;

  return (
    <div>
      <PageHeader
        title="Audit Logs"
        subtitle="Immutable trail of every security-relevant action. Master Admin only."
        actions={
          <Button
            variant="secondary"
            onClick={async () => {
              try {
                await download(
                  `/audit-logs/export.csv${resultFilter ? `?result=${resultFilter}` : ""}`,
                  "audit-logs.csv",
                );
              } catch {
                toast("error", "Export failed");
              }
            }}
            data-testid="export-audit"
          >
            Export CSV
          </Button>
        }
      />

      <div className="mb-3 flex gap-2">
        {["", "SUCCESS", "FAILURE", "DENIED"].map((r) => (
          <Button
            key={r || "all"}
            variant={resultFilter === r ? "primary" : "secondary"}
            onClick={() => setResultFilter(r)}
          >
            {r || "All"}
          </Button>
        ))}
      </div>

      <Card className="overflow-hidden">
        {(data?.items.length ?? 0) === 0 ? (
          <EmptyState title="No audit entries match this filter" />
        ) : (
          <div className="ag-theme-quartz h-[65vh] w-full">
            <AgGridReact
              rowData={data?.items ?? []}
              columnDefs={columnDefs}
              pagination
              paginationPageSize={100}
              defaultColDef={{ sortable: true, filter: true, resizable: true }}
            />
          </div>
        )}
      </Card>
    </div>
  );
}
