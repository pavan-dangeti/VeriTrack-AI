import { useParams, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  AlertOctagon,
  ArrowLeft,
  CheckCircle2,
  FileDown,
  FileSpreadsheet,
  Mail,
  MailWarning,
  UserX,
} from "lucide-react";
import { ApiError, download } from "../api/client";
import { endpoints } from "../api/endpoints";
import { errorMessage } from "../api/hooks";
import { Badge, Button, Card, EmptyState, PageHeader, SectionTitle, Stat, StatusBadge } from "../components/ui/kit";
import { useToast } from "../components/ui/toast";
import { fmtDate, fmtDateTime } from "../lib/format";

const SKIP_LABEL: Record<string, string> = {
  NOT_IN_REPO: "Not in your repository",
  BAD_ID_FORMAT: "Unreadable employee ID",
  NEEDS_REVIEW: "Extraction needs review",
  MISSING_COLUMNS: "Leave columns missing",
};

export function AnalysisResultsPage() {
  const { batchId = "" } = useParams();
  const navigate = useNavigate();
  const toast = useToast();
  const { data, isLoading, error } = useQuery({
    queryKey: ["analysis", batchId],
    queryFn: () => endpoints.analysis(batchId),
    // the run row exists as soon as analysis is accepted, so 404 is final
    retry: (count, err) => !(err instanceof ApiError && err.status < 500) && count < 2,
    refetchInterval: (q) => (q.state.data?.status === "RUNNING" ? 2000 : false),
  });

  if (isLoading || data?.status === "RUNNING") {
    return (
      <Card className="p-10 text-center" data-testid="analysis-running">
        <div className="mx-auto mb-4 h-10 w-10 animate-spin rounded-full border-4 border-primary-100 border-t-primary-600" />
        <p className="font-semibold text-ink">Running analysis…</p>
        <p className="mt-1 text-sm text-ink-3">Matching GETS leave against the company leave register. This page updates automatically.</p>
      </Card>
    );
  }
  if (error || !data) {
    return (
      <Card>
        <EmptyState title="No analysis for this batch yet" hint={errorMessage(error)} />
      </Card>
    );
  }

  const t = data.totals;
  const short = data.run_id.slice(0, 8);
  return (
    <div data-testid="analysis-page">
      <button onClick={() => navigate(-1)} className="mb-4 inline-flex items-center gap-1.5 text-sm text-ink-2 hover:text-ink">
        <ArrowLeft className="h-4 w-4" /> Back
      </button>
      <PageHeader
        eyebrow={`Run ${short} · ${fmtDateTime(data.completed_at ?? data.started_at)}`}
        title="Analysis results"
        subtitle="Customer leave (GETS Out Of Office) compared with the company leave register."
        actions={
          <>
            <Button variant="secondary" icon={FileDown} onClick={() => download(`/runs/${data.run_id}/reports/summary.pdf`, `summary-${short}.pdf`).catch((e) => toast("error", errorMessage(e)))}>
              Summary PDF
            </Button>
            <Button variant="secondary" icon={FileSpreadsheet} onClick={() => download(`/runs/${data.run_id}/reports/3tab.xlsx`, `report-${short}.xlsx`).catch((e) => toast("error", errorMessage(e)))}>
              Excel report
            </Button>
          </>
        }
      />
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Stat label="Employees checked" value={t.matched} icon={CheckCircle2} tone="success" />
        <Stat label="Violations" value={t.violations} icon={AlertOctagon} tone={t.violations ? "danger" : "success"} />
        <Stat label="Emails sent" value={t.emails_sent} icon={Mail} />
        <Stat label="Skipped" value={t.skipped} icon={UserX} tone={t.skipped ? "warning" : "primary"} hint={t.emails_missing ? `${t.emails_missing} without email` : undefined} />
      </div>

      <SectionTitle>Violations</SectionTitle>
      {data.violations.length === 0 ? (
        <Card>
          <EmptyState icon={CheckCircle2} title="No violations" hint="Every Out Of Office day has a matching company leave entry." />
        </Card>
      ) : (
        <Card className="overflow-x-auto">
          <table className="data-table" data-testid="violations-table">
            <thead>
              <tr>
                <th>Employee</th>
                <th>Leave in GETS</th>
                <th>Missing in register</th>
                <th>Notification</th>
              </tr>
            </thead>
            <tbody>
              {data.violations.map((v) => {
                const missing = v.details?.missing_in_register ?? [];
                const customer = v.details?.customer_leave_dates ?? (v.customer_leave_value ? [v.customer_leave_value] : []);
                return (
                  <tr key={v.employee_code}>
                    <td>
                      <p className="font-medium text-ink">{v.employee_name ?? "—"}</p>
                      <p className="font-mono text-xs text-ink-3">{v.employee_code}</p>
                    </td>
                    <td>
                      <div className="flex max-w-xs flex-wrap gap-1">
                        {customer.map((d) => <Badge key={d}>{fmtDate(d, { year: undefined })}</Badge>)}
                      </div>
                    </td>
                    <td>
                      {missing.length ? (
                        <div className="flex max-w-xs flex-wrap gap-1">
                          {missing.map((d) => <Badge key={d} tone="danger">{fmtDate(d, { year: undefined })}</Badge>)}
                        </div>
                      ) : (
                        <span className="text-sm text-ink-2">{v.violation_reason}</span>
                      )}
                    </td>
                    <td>
                      <div className="flex items-center gap-2">
                        {v.email_status === "SKIPPED_NO_EMAIL" ? <MailWarning className="h-4 w-4 text-warning-700" /> : <Mail className="h-4 w-4 text-ink-3" />}
                        <div>
                          <StatusBadge status={v.email_status} />
                          {v.email_to && <p className="mt-0.5 text-xs text-ink-3">{v.email_to}</p>}
                        </div>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </Card>
      )}

      {data.skipped_rows.length > 0 && (
        <>
          <SectionTitle>Skipped ({data.skipped_rows.length})</SectionTitle>
          <Card className="overflow-x-auto">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Employee ID</th>
                  <th>Reason</th>
                  <th>Details</th>
                </tr>
              </thead>
              <tbody>
                {data.skipped_rows.map((s, i) => (
                  <tr key={i}>
                    <td className="font-mono">{s.employee_code || "—"}</td>
                    <td><Badge tone="warning">{SKIP_LABEL[s.status] ?? s.status}</Badge></td>
                    <td className="text-xs">{s.reason ?? ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        </>
      )}
    </div>
  );
}
