import { useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  BarChart3,
  CheckCircle2,
  ChevronDown,
  Download,
  Eye,
  FileImage,
  FileSpreadsheet,
  Play,
  RefreshCcw,
  ScanLine,
  ShieldCheck,
} from "lucide-react";
import { api, ApiError, download } from "../api/client";
import { endpoints, type Batch, type BatchFile } from "../api/endpoints";
import { errorMessage, useBatchDetail, useBatches, useUploadBatch } from "../api/hooks";
import {
  Badge,
  Button,
  Card,
  Dropzone,
  EmptyState,
  PageHeader,
  ProgressBar,
  ReviewBadge,
  Skeleton,
  StatusBadge,
} from "../components/ui/kit";
import { useToast } from "../components/ui/toast";
import { fmtBytes, fmtDateTime, fmtPeriod, timeAgo } from "../lib/format";

const ALLOWED = ["png", "jpg", "jpeg", "pdf", "xlsx", "xls", "csv"];

const STEPS = [
  { icon: ScanLine, title: "Upload screenshots", text: "GETS timesheet screenshots, PDFs or exports — up to 20 per batch." },
  { icon: ShieldCheck, title: "Verified extraction", text: "Every hour is cross-checked against the sheet's own totals." },
  { icon: BarChart3, title: "Run analysis", text: "Out Of Office days are matched against the company leave register." },
];

export function GetsUploadsPage({ crossManager = false }: { crossManager?: boolean }) {
  const { data: allBatches, isLoading } = useBatches();
  const toast = useToast();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [open, setOpen] = useState<string | null>(null);
  const uploadMut = useUploadBatch("GETS");

  const batches = (allBatches ?? []).filter((b) => b.kind === "GETS" || !b.kind);

  // A double-click fires two click events before the mutation's pending
  // state re-renders the button as disabled — gate synchronously so only
  // one analyze request is ever sent.
  const analyzeLock = useRef(false);
  const analyze = useMutation({
    mutationFn: (batchId: string) => endpoints.analyze(batchId),
    onSettled: () => {
      analyzeLock.current = false;
    },
    onSuccess: (res, batchId) => {
      const r = res as { status?: string; violations?: number };
      toast(
        "success",
        r?.status === "RUNNING"
          ? "Analysis started — results update live"
          : `Analysis complete${r?.violations != null ? ` · ${r.violations} violation(s)` : ""}`,
      );
      qc.invalidateQueries({ queryKey: ["analysis", batchId] });
      navigate(`/analysis/${batchId}`);
    },
    onError: (e, batchId) => {
      if (e instanceof ApiError && e.code === "already_analyzed") {
        navigate(`/analysis/${batchId}`);
        return;
      }
      toast("error", errorMessage(e));
    },
  });

  if (isLoading) return <Skeleton rows={6} />;

  return (
    <div>
      <PageHeader
        eyebrow={crossManager ? "Organisation" : "Workspace"}
        title={crossManager ? "All GETS Uploads" : "GETS Uploads"}
        subtitle={
          crossManager
            ? "Every GETS batch across managers, with extraction verification status."
            : "Upload monthly GETS timesheets. Extraction runs in the background and is verified against each sheet's totals."
        }
      />

      {!crossManager && (
        <div className="mb-8 grid gap-4 lg:grid-cols-[1.2fr_1fr]">
          <Dropzone
            accept={ALLOWED}
            busy={uploadMut.isPending}
            testId="gets-file-input"
            title="Drop GETS screenshots here or click to browse"
            hint="PNG · JPG · PDF · XLSX · XLS · CSV — max 20 files, 25 MB each"
            onFiles={(files) =>
              uploadMut.mutate(files, {
                onSuccess: (batch) => {
                  setOpen(batch.id);
                  toast("info", `${batch.total_files} file(s) queued — live progress below`);
                },
                onError: (e) => toast("error", errorMessage(e)),
              })
            }
          />
          <Card className="grid gap-4 p-5 sm:grid-cols-3 lg:grid-cols-1">
            {STEPS.map((s, i) => (
              <div key={s.title} className="flex gap-3">
                <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-primary-50 text-primary-600">
                  <s.icon className="h-4.5 w-4.5" aria-hidden />
                </span>
                <div>
                  <p className="text-sm font-semibold text-ink">
                    <span className="mr-1 text-ink-3">{i + 1}.</span>
                    {s.title}
                  </p>
                  <p className="text-xs text-ink-3">{s.text}</p>
                </div>
              </div>
            ))}
          </Card>
        </div>
      )}

      {batches.length === 0 ? (
        <Card>
          <EmptyState
            icon={FileSpreadsheet}
            title="No GETS uploads yet"
            hint={crossManager ? "Batches appear here as managers upload." : "Upload your first monthly GETS sheet to begin."}
          />
        </Card>
      ) : (
        <div className="space-y-3">
          {batches.map((batch) => (
            <BatchCard
              key={batch.id}
              batch={batch}
              crossManager={crossManager}
              expanded={open === batch.id}
              onToggle={() => setOpen((o) => (o === batch.id ? null : batch.id))}
              analyzing={analyze.isPending && analyze.variables === batch.id}
              onAnalyze={() => {
                if (analyzeLock.current) return;
                analyzeLock.current = true;
                analyze.mutate(batch.id);
              }}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function BatchCard({
  batch,
  crossManager,
  expanded,
  onToggle,
  analyzing,
  onAnalyze,
}: {
  batch: Batch;
  crossManager: boolean;
  expanded: boolean;
  onToggle: () => void;
  analyzing: boolean;
  onAnalyze: () => void;
}) {
  const done = batch.processed_files + batch.failed_files;
  const moving = batch.status === "PROCESSING" || batch.status === "QUEUED";
  const toast = useToast();
  return (
    <Card className="overflow-hidden" data-testid={`batch-${batch.id}`}>
      <div className="flex flex-col gap-4 p-4 sm:p-5 lg:flex-row lg:items-center">
        <div className="flex min-w-0 flex-1 items-center gap-4">
          <span className="hidden h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-primary-50 text-primary-600 sm:flex">
            <FileSpreadsheet className="h-5 w-5" aria-hidden />
          </span>
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <StatusBadge status={batch.status} />
              <span className="text-sm font-medium text-ink">
                {batch.total_files} file{batch.total_files === 1 ? "" : "s"}
              </span>
              {batch.failed_files > 0 && <Badge tone="danger">{batch.failed_files} failed</Badge>}
              {crossManager && batch.manager_email && (
                <span className="truncate text-sm text-ink-2" data-testid={`uploader-${batch.id}`}>
                  {batch.manager_name && batch.manager_name !== batch.manager_email ? `${batch.manager_name} · ` : ""}
                  <span className="text-ink-3">{batch.manager_email}</span>
                </span>
              )}
              <span className="text-xs text-ink-3" title={fmtDateTime(batch.created_at)}>
                {timeAgo(batch.created_at)}
              </span>
            </div>
            <div className="mt-2.5 flex items-center gap-3">
              <div className="max-w-xs flex-1">
                <ProgressBar value={done} max={batch.total_files} tone={batch.failed_files ? "warning" : moving ? "primary" : "success"} />
              </div>
              <span className="text-xs tabular-nums text-ink-3">
                {batch.processed_files}/{batch.total_files} files processed
              </span>
            </div>
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button variant="secondary" icon={Eye} onClick={onToggle} data-testid="inspect" aria-expanded={expanded}>
            {expanded ? "Hide files" : "Inspect files"}
            <ChevronDown className={`h-4 w-4 transition ${expanded ? "rotate-180" : ""}`} aria-hidden />
          </Button>
          {batch.status === "COMPLETED" && (
            <>
              <Button
                variant="secondary"
                icon={Download}
                onClick={() =>
                  download(`/batches/${batch.id}/export?format=xlsx`, "gets-export.xlsx").catch((e) =>
                    toast("error", errorMessage(e)),
                  )
                }
              >
                Export
              </Button>
              {!crossManager ? (
                <Button icon={Play} onClick={onAnalyze} loading={analyzing} data-testid={`analyze-${batch.id}`}>
                  {analyzing ? "Analyzing…" : "Run analysis"}
                </Button>
              ) : (
                <Link to={`/analysis/${batch.id}`}>
                  <Button variant="ghost" icon={BarChart3}>Results</Button>
                </Link>
              )}
            </>
          )}
        </div>
      </div>
      {expanded && <BatchFiles batchId={batch.id} canReprocess={!crossManager} />}
    </Card>
  );
}

function SheetBadge({ file }: { file: BatchFile }) {
  if (!file.sheet_status) return null;
  const map = {
    VERIFIED: { tone: "success" as const, label: "Totals verified" },
    CORRECTED: { tone: "primary" as const, label: "Verified · auto-corrected" },
    NEEDS_REVIEW: { tone: "warning" as const, label: "Totals mismatch" },
  };
  const s = map[file.sheet_status];
  return (
    <Badge tone={s.tone}>
      {file.sheet_status !== "NEEDS_REVIEW" && <CheckCircle2 className="h-3 w-3" aria-hidden />}
      {s.label}
    </Badge>
  );
}

function BatchFiles({ batchId, canReprocess }: { batchId: string; canReprocess: boolean }) {
  const { data } = useBatchDetail(batchId);
  const qc = useQueryClient();
  const toast = useToast();

  const reprocess = useMutation({
    mutationFn: (fileId: string) =>
      api(`/uploads/batches/${batchId}/files/${fileId}/reprocess?force=true`, { method: "POST" }),
    onSuccess: () => {
      toast("success", "Re-extraction complete");
      qc.invalidateQueries({ queryKey: ["batch", batchId] });
      qc.invalidateQueries({ queryKey: ["batches"] });
    },
    onError: (e) => toast("error", errorMessage(e)),
  });

  return (
    <div className="border-t border-line bg-surface-2/60" data-testid="progress-card">
      {!data?.files ? (
        <Skeleton rows={2} />
      ) : (
        <div className="overflow-x-auto">
          <table className="data-table">
            <thead>
              <tr>
                <th>File</th>
                <th>Employee · period</th>
                <th>Rows</th>
                <th>Extraction</th>
                <th className="text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {data.files.map((f) => (
                <tr key={f.id}>
                  <td>
                    <div className="flex items-center gap-2.5">
                      <FileImage className="h-4 w-4 shrink-0 text-ink-3" aria-hidden />
                      <div className="min-w-0">
                        <p className="truncate font-medium text-ink">{f.original_filename}</p>
                        <p className="text-xs text-ink-3">{fmtBytes(f.file_size)}</p>
                      </div>
                    </div>
                  </td>
                  <td>
                    {f.sheet_employee ? (
                      <>
                        <p className="text-ink">{f.sheet_employee}</p>
                        <p className="text-xs text-ink-3">{fmtPeriod(f.sheet_period)}</p>
                      </>
                    ) : (
                      <span className="text-ink-3">—</span>
                    )}
                  </td>
                  <td className="tabular-nums">
                    {f.rows_extracted ?? "—"}
                    {f.needs_review_count > 0 && (
                      <span className="ml-2 text-xs font-medium text-warning-700">{f.needs_review_count} need review</span>
                    )}
                  </td>
                  <td>
                    <div className="flex flex-wrap items-center gap-1.5">
                      <StatusBadge status={f.status} />
                      <SheetBadge file={f} />
                      {f.needs_review_count > 0 && <ReviewBadge note={`${f.needs_review_count} rows flagged`} />}
                    </div>
                    {f.error_message && <p className="mt-1 max-w-xs truncate text-xs text-danger-700" title={f.error_message}>{f.error_message}</p>}
                  </td>
                  <td>
                    <div className="flex justify-end gap-1">
                      {f.status === "DONE" && (
                        <Link to={`/review/${batchId}/${f.id}`}>
                          <Button variant="ghost" size="sm" icon={Eye} data-testid={`review-${f.id}`}>Review</Button>
                        </Link>
                      )}
                      {canReprocess && (f.status === "DONE" || f.status === "FAILED" || f.status === "PENDING_OCR") && (
                        <Button
                          variant="ghost"
                          size="sm"
                          icon={RefreshCcw}
                          loading={reprocess.isPending && reprocess.variables === f.id}
                          onClick={() => reprocess.mutate(f.id)}
                          data-testid={`reextract-${f.id}`}
                        >
                          Re-extract
                        </Button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
