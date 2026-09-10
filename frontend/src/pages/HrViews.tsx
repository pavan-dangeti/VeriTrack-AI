import { download } from "../api/client";
import { useEmployees, type Employee } from "../api/hooks";
import { Button, Card, EmptyState, PageHeader, Skeleton, StatusBadge } from "../components/ui/kit";

/** HR: read-only view of the manager's employee data (search + download only). */
export function EmployeeDataPage() {
  const { data, isLoading } = useEmployees();
  if (isLoading) return <Skeleton rows={6} />;
  const items = data?.items ?? [];
  return (
    <div>
      <PageHeader
        title="Employee Data"
        subtitle="Read-only view of your manager's employee repository."
        actions={
          <Button variant="secondary" onClick={() => download("/batches/export?format=csv", "employees.csv").catch(() => {})}>
            Download CSV
          </Button>
        }
      />
      <Card className="overflow-hidden">
        {items.length === 0 ? (
          <EmptyState title="No employees uploaded yet" hint="Your manager has not uploaded a repository." />
        ) : (
          <table className="data-table" data-testid="hr-employees">
            <thead>
              <tr>
                <th>Employee ID</th>
                <th>Name</th>
                <th>Company Email</th>
                <th>Personal Email</th>
                <th>Department</th>
              </tr>
            </thead>
            <tbody>
              {items.map((e: Employee) => (
                <tr key={e.id}>
                  <td>{e.employee_code}</td>
                  <td>{e.full_name}</td>
                  <td>{e.official_email ?? "—"}</td>
                  <td>{e.personal_email ?? "—"}</td>
                  <td>{e.department ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </div>
  );
}

/** HR: read-only GETS sheet downloads — no upload/analyze controls rendered at all. */
export function GetsSheetsPage() {
  const batches = useBatchesReadOnly();
  if (batches.isLoading) return <Skeleton rows={5} />;
  const getses = (batches.data ?? []).filter((b) => b.kind === "GETS");
  return (
    <div>
      <PageHeader title="Monthly GETS Sheets" subtitle="Download-only access to processed GETS exports." />
      {getses.length === 0 ? (
        <Card><EmptyState title="No GETS sheets available yet" /></Card>
      ) : (
        <div className="space-y-3">
          {getses.map((b) => (
            <Card key={b.id} className="flex items-center justify-between p-4">
              <div className="flex items-center gap-3 text-sm">
                <StatusBadge status={b.status} />
                <span>{new Date(b.created_at).toLocaleDateString()}</span>
                <span className="text-gray-400">{b.total_files} files</span>
              </div>
              <Button variant="secondary" onClick={() => download(`/batches/${b.id}/export?format=xlsx`, `gets-${b.id.slice(0, 8)}.xlsx`)}>
                Download export
              </Button>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}

import { useQuery } from "@tanstack/react-query";
import { endpoints as ep } from "../api/endpoints";

function useBatchesReadOnly() {
  return useQuery({
    queryKey: ["batches-hr"],
    queryFn: () => ep.batches(),
    refetchInterval: false,
  });
}
