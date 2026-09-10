import { useQueryClient } from "@tanstack/react-query";
import { api, download } from "../api/client";
import { useApiQuery, type RunDetail } from "../api/endpoints";
import { errorMessage } from "../api/hooks";
import { Button, Card, EmptyState, PageHeader, Skeleton } from "../components/ui/kit";
import { useToast } from "../components/ui/toast";

/** Lists completed analyses with downloads + resend. Works cross-manager for MA/EXEC. */
export function ReportsPage({ crossManager = false }: { crossManager?: boolean }) {
  const batchesQ = useApiQuery<{ id: string; status: string; kind: string }[]>(
    ["batches-for-reports"],
    "/uploads/batches",
  );
  const qc = useQueryClient();

  if (batchesQ.isLoading) return <Skeleton rows={6} />;

  const getses = (batchesQ.data ?? []).filter((b) => b.kind === "GETS");
  return (
    <div>
      <PageHeader
        title={crossManager ? "All Reports" : "Reports & History"}
        subtitle={
          crossManager
            ? "Every completed analysis across managers. Download or mirror reports."
            : "Past Analyze runs — download the summary PDF and 3-tab Excel."
        }
      />
      {getses.length === 0 ? (
        <Card>
          <EmptyState title="No GETS batches yet" hint="Run an analysis to generate your first report." />
        </Card>
      ) : (
        <div className="space-y-4">
          {getses.map((batch) => (
            <ReportRow key={batch.id} batchId={batch.id} onResent={() => qc.invalidateQueries()} />
          ))}
        </div>
      )}
    </div>
  );
}

function ReportRow({
  batchId,
  onResent,
}: {
  batchId: string;
  onResent: () => void;
}) {
  const { data: run, isLoading } = useApiQuery<RunDetail>(
    ["analysis", batchId],
    `/batches/${batchId}/analysis`,
    { retry: false },
  );
  const toast = useToast();
  if (isLoading) return <Skeleton rows={2} />;
  if (!run) return null;

  const t = run.totals;
  return (
    <Card className="p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="text-sm text-gray-600">
          <span className="font-mono text-xs text-gray-400">run {run.run_id.slice(0, 8)}</span>
          <span className="ml-3">
            {t.rows_processed} rows · {t.violations} violations ·{" "}
            {t.emails_sent} sent · {t.emails_missing} no-email · {t.skipped} skipped
          </span>
        </div>
        <div className="flex gap-2">
          <Button variant="secondary" onClick={() => download(`/runs/${run.run_id}/reports/summary.pdf`, `summary-${run.run_id.slice(0, 8)}.pdf`)}>
            Summary PDF
          </Button>
          <Button variant="secondary" onClick={() => download(`/runs/${run.run_id}/reports/3tab.xlsx`, `report-${run.run_id.slice(0, 8)}.xlsx`)} data-testid={`download-xlsx-${run.run_id.slice(0, 8)}`}>
            3-tab Excel
          </Button>
          <Button
            variant="ghost"
            onClick={async () => {
              try {
                  const csrf = await api<{ csrf_token: string }>("/auth/csrf", { method: "POST" });
                await api(`/runs/${run.run_id}/resend`, {
                  method: "POST",
                  headers: { "X-CSRF-Token": csrf.csrf_token },
                });
                toast("success", "Reports re-delivered to the manager");
                onResent();
              } catch (e) {
                toast("error", errorMessage(e));
              }
            }}
          >
            Resend
          </Button>
        </div>
      </div>
    </Card>
  );
}
