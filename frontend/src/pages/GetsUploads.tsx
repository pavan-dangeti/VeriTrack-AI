import { useEffect, useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { endpoints, type Batch } from "../api/endpoints";
import { useBatchDetail, useBatches } from "../api/hooks";
import { errorMessage, useBatchCompletionWatcher } from "../api/hooks";
import { download, getAccessToken } from "../api/client";
import {
  Button,
  Card,
  EmptyState,
  PageHeader,
  ReviewBadge,
  Skeleton,
  StatusBadge,
} from "../components/ui/kit";
import { useToast } from "../components/ui/toast";

const ALLOWED = ["pdf", "xlsx", "xls", "csv", "png", "jpg", "jpeg"];

export function GetsUploadsPage({ crossManager = false }: { crossManager?: boolean }) {
  const { data: batches, isLoading } = useBatches();
  const toast = useToast();
  const qc = useQueryClient();
  const fileInput = useRef<HTMLInputElement>(null);
  const [activeBatch, setActiveBatch] = useState<string | null>(null);
  const [analyzing, setAnalyzing] = useState<string | null>(null);

  // Cross-page completion toasts (3b): fires even if user navigates away.
  useBatchCompletionWatcher(({ status, failed }) => {
    qc.invalidateQueries({ queryKey: ["batches"] });
    if (status === "COMPLETED") toast("success", "GETS batch processing complete");
    else if (status === "FAILED")
      toast("error", `GETS batch processing failed (${failed} files)`);
  });

  const upload = useMutation({
    mutationFn: async (files: FileList) => {
      const fd = new FormData();
      for (const f of Array.from(files)) fd.append("files", f);
      return fetch(`/api/v1/uploads?kind=GETS`, {
        method: "POST",
        headers: { Authorization: `Bearer ${getAccessToken() ?? ""}` },
        body: fd,
      }).then(async (r) => {
        if (!r.ok) throw new Error((await r.json()).error?.message ?? "Upload rejected");
        return r.json() as Promise<Batch>;
      });
    },
    onSuccess: (batch) => {
      setActiveBatch(batch.id);
      qc.invalidateQueries({ queryKey: ["batches"] });
      toast("info", `${batch.total_files} files queued — live progress below`);
    },
    onError: (e) => toast("error", errorMessage(e)),
  });

  const analyze = useMutation({
    mutationFn: (batchId: string) => endpoints.analyze(batchId),
    onSuccess: () => {
      setAnalyzing(null);
      toast("success", "Analysis complete — see Reports & History");
      qc.invalidateQueries({ queryKey: ["batches"] });
    },
    onError: (e) => {
      setAnalyzing(null);
      toast("error", errorMessage(e));
    },
  });

  if (isLoading) return <Skeleton rows={6} />;

  return (
    <div>
      <PageHeader
        title={crossManager ? "All GETS Uploads" : "GETS Uploads"}
        subtitle={
          crossManager
            ? "Cross-manager view of every GETS batch and its processing state."
            : "Upload monthly GETS sheets (PDF/XLSX/CSV — up to 20 files). Processing runs sequentially per file."
        }
        actions={
          !crossManager && (
            <>
              <input
                ref={fileInput}
                type="file"
                multiple
                accept={ALLOWED.map((e) => "." + e).join(",")}
                className="hidden"
                onChange={(e) => e.target.files?.length && upload.mutate(e.target.files)}
                data-testid="gets-file-input"
              />
              <Button onClick={() => fileInput.current?.click()} disabled={upload.isPending}>
                {upload.isPending ? "Uploading…" : "Upload GETS files"}
              </Button>
            </>
          )
        }
      />

      {!crossManager && activeBatch && (
        <BatchProgressCard batchId={activeBatch} onDone={() => setActiveBatch(null)} />
      )}

      {(batches?.length ?? 0) === 0 ? (
        <Card>
          <EmptyState
            title="No GETS uploads yet"
            hint={crossManager ? "Batches appear here as managers upload." : "Upload your first monthly GETS sheet to begin."}
          />
        </Card>
      ) : (
        <div className="space-y-4">
          {batches!.map((batch) => (
            <BatchRow
              key={batch.id}
              batch={batch}
              crossManager={crossManager}
              analyzing={analyzing === batch.id}
              onAnalyze={() => {
                setAnalyzing(batch.id);
                analyze.mutate(batch.id);
              }}
              onInspect={() => setActiveBatch(batch.id)}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function BatchRow({
  batch,
  crossManager,
  analyzing,
  onAnalyze,
  onInspect,
}: {
  batch: Batch;
  crossManager: boolean;
  analyzing: boolean;
  onAnalyze: () => void;
  onInspect: () => void;
}) {
  const flagged = batch.files?.reduce((n, f) => n + f.needs_review_count, 0) ?? 0;
  return (
    <Card className="p-4" data-testid={`batch-${batch.id}`}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <StatusBadge status={batch.status} />
          {crossManager && batch.manager_email && (
            <span className="text-sm text-gray-700" data-testid={`uploader-${batch.id}`}>
              {batch.manager_name && batch.manager_name !== batch.manager_email
                ? `${batch.manager_name} · `
                : ""}
              <span className="text-gray-500">{batch.manager_email}</span>
            </span>
          )}
          <span className="text-sm text-gray-600">
            {batch.processed_files}/{batch.total_files} files processed
            {batch.failed_files > 0 && (
              <span className="ml-2 text-danger-700">{batch.failed_files} failed</span>
            )}
          </span>
          {flagged > 0 && (
            <>
              <ReviewBadge note={`${flagged} extracted rows flagged for review`} />
              <span className="text-xs text-warning-700">{flagged} rows need review</span>
            </>
          )}
          <span className="text-xs text-gray-400">
            {new Date(batch.created_at).toLocaleString()}
          </span>
        </div>
        {!crossManager && batch.status === "COMPLETED" && (
          <div className="flex gap-2">
             <Button variant="secondary" onClick={onInspect} data-testid="inspect">
              Inspect files
            </Button>
            <Button variant="secondary" onClick={() => download(`/batches/${batch.id}/export?format=xlsx`, "gets-export.xlsx").catch(() => {})}>
              Print/Export
            </Button>
            <Button onClick={onAnalyze} disabled={analyzing} data-testid={`analyze-${batch.id}`}>
              {analyzing ? "Analyzing…" : "Run Analyze"}
            </Button>
          </div>
        )}
      </div>
    </Card>
  );
}

function BatchProgressCard({ batchId, onDone }: { batchId: string; onDone: (b: Batch) => void }) {
  const { data } = useBatchDetail(batchId);
  const qc = useQueryClient();
  const toast = useToast();
  const prevStatus = useRef<string | undefined>(undefined);

  const reprocess = useMutation({
    mutationFn: (fileId: string) =>
      fetch(`/api/v1/uploads/batches/${batchId}/files/${fileId}/reprocess?force=true`, {
        method: "POST",
        headers: { Authorization: `Bearer ${getAccessToken() ?? ""}` },
      }).then(async (r) => {
        if (!r.ok) throw new Error((await r.json()).error?.message ?? "Re-extract failed");
        return r.json();
      }),
    onSuccess: () => {
      toast("success", "Re-extraction complete");
      qc.invalidateQueries({ queryKey: ["batch", batchId] });
      qc.invalidateQueries({ queryKey: ["batches"] });
    },
    onError: (e) => toast("error", errorMessage(e)),
  });

  // Auto-close only when a live PROCESSING batch settles; an opened DONE batch
  // stays up as an inspect panel (so Re-extract can be used).
  useEffect(() => {
    const cur = data?.status;
    if (prevStatus.current === "PROCESSING" && cur && cur !== "PROCESSING") {
      const t = setTimeout(() => onDone(data!), 1500);
      prevStatus.current = cur;
      return () => clearTimeout(t);
    }
    prevStatus.current = cur;
  }, [data?.status, data, onDone]);

  return (
    <Card className="mb-4 p-4" data-testid="progress-card">
      <p className="mb-2 text-sm font-medium text-gray-700">
        {data?.status === "PROCESSING" ? "Live processing progress" : "Files"}
      </p>
      <div className="space-y-2">
        {data?.files?.map((f) => (
          <div key={f.id} className="flex items-center justify-between rounded-lg bg-canvas px-3 py-2">
            <span className="text-sm text-gray-700">{f.original_filename}</span>
            <div className="flex items-center gap-3 text-xs text-gray-500">
              {f.rows_extracted != null && <span>{f.rows_extracted} rows</span>}
              {f.needs_review_count > 0 && (
                <span className="font-medium text-warning-700">
                  {f.needs_review_count} need review
                </span>
              )}
              <StatusBadge status={f.status} />
              {f.status === "DONE" && (
                <Button
                  variant="ghost"
                  className="!px-2 !py-1 !text-xs"
                  disabled={reprocess.isPending}
                  onClick={() => reprocess.mutate(f.id)}
                  data-testid={`reextract-${f.id}`}
                >
                  {reprocess.isPending ? "Re-extracting…" : "Re-extract"}
                </Button>
              )}
            </div>
          </div>
        )) ?? <Skeleton rows={1} />}
      </div>
    </Card>
  );
}
