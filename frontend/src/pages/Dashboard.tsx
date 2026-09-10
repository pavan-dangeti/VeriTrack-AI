import { useApiQuery } from "../api/endpoints";
import { Card, PageHeader, ReviewBadge, SectionTitle, Skeleton, Stat } from "../components/ui/kit";

export function DashboardPage() {
  const { data, isLoading } = useApiQuery<Record<string, any>>(
    ["summary"],
    "/dashboard/summary",
    { refetchInterval: 15_000 },
  );
  if (isLoading || !data) return <Skeleton rows={6} />;

  const isHr = data.role === "HR";
  const exec = data.role === "MASTER_ADMIN" || data.role === "EXECUTIVE";

  const cards = [
    { label: "Employees", value: data.employees_total },
    { label: "Batches uploaded", value: data.batches_total },
    ...(isHr
      ? []
      : [
          { label: "Analysis runs", value: data.analysis_runs_completed },
          { label: "Violations detected", value: data.violations_detected },
          { label: "Emails sent", value: data.emails_sent },
        ]),
  ];

  return (
    <div>
      <PageHeader
        title={isHr ? "Team Overview" : "Dashboard"}
        subtitle={`Scope: ${data.scope}`}
      />

      {Number(data.employees_needing_review) > 0 && (
        <div className="mb-6 flex items-center gap-3 rounded-xl border border-warning-700/30 bg-warning-100 px-4 py-3">
          <ReviewBadge note={`${data.employees_needing_review} employee records were flagged during OCR extraction`} />
          <span className="text-sm text-warning-700">
            {data.employees_needing_review} record(s) need review before analysis accuracy is guaranteed.
          </span>
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-5">
        {cards.map((c) => (
          <div key={c.label} data-testid={`metric-${c.label}`}>
            <Stat label={c.label} value={c.value ?? "—"} />
          </div>
        ))}
      </div>

      {data.users_by_role && exec && (
        <>
          <SectionTitle>Active accounts by role</SectionTitle>
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
            {Object.entries(data.users_by_role as Record<string, number>).map(([role, n]) => (
              <Stat key={role} label={role.replace("_", " ")} value={n} />
            ))}
          </div>
        </>
      )}

      {isHr && data.latest_gets_batch && (
        <Card className="mt-6 p-5">
          <p className="text-sm text-gray-500">Latest GETS batch (your manager)</p>
          <p className="mt-1 font-medium" data-testid="hr-latest-batch">
            Status: {data.latest_gets_batch.status} ·{" "}
            {new Date(data.latest_gets_batch.created_at).toLocaleDateString()}
          </p>
        </Card>
      )}
    </div>
  );
}
