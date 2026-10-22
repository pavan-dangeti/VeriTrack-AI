import { useEffect, useRef } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, upload } from "./client";
import { endpoints, type Batch, type Employee } from "./endpoints";
export type { Employee } from "./endpoints";

const inFlight = (s?: string) => s === "PROCESSING" || s === "QUEUED";

/**
 * How often to poll while work is in flight: every 1.5 s at first, slowing as the newest in-flight item ages,
 * to every 10 s once it has waited a minute. At a fixed 1.5 s, hundreds of open pages polling were most of
 * the API's load in the 200-user load test, and starved the OCR they were waiting for.
 */
export function pollDelay(createdAt: (string | null | undefined)[], now = Date.now()): number {
  const ages = createdAt.filter((c): c is string => !!c).map((c) => now - Date.parse(c));
  const age = ages.length ? Math.min(...ages) : 0;
  return Math.min(10_000, Math.max(1_500, Math.round(age / 6)));
}

const inFlightDelay = (batches: Batch[]) => {
  const moving = batches.filter((b) => inFlight(b.status));
  return moving.length ? pollDelay(moving.map((b) => b.created_at)) : false;
};

export function useBatches(kind?: string) {
  return useQuery({
    queryKey: ["batches", kind],
    queryFn: () => endpoints.batches(kind),
    staleTime: 5_000,
    refetchInterval: (query) => {
      return inFlightDelay((query.state.data as Batch[] | undefined) ?? []);
    },
  });
}

export function useBatchDetail(batchId: string | null) {
  return useQuery({
    queryKey: ["batch", batchId],
    queryFn: () => endpoints.batch(batchId!),
    enabled: !!batchId,
    refetchInterval: (query) => {
      const d = query.state.data as Batch | undefined;
      const moving = inFlight(d?.status) || d?.files?.some((f) => inFlight(f.status));
      return moving && d ? pollDelay([d.created_at]) : false;
    },
  });
}

export function useEmployees() {
  return useQuery({
    queryKey: ["employees"],
    queryFn: () => api<{ items: Employee[]; total: number }>("/employees"),
    staleTime: 10_000,
  });
}

export function useUploadBatch(kind: "TIMESHEET" | "EMPLOYEE_REPO" | "COMPANY_LEAVE") {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (files: File[]) => upload<Batch>(`/uploads?kind=${kind}`, files),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["batches"] });
      // wake the completion watcher now instead of on its 15 s idle poll
      qc.invalidateQueries({ queryKey: ["batches-watcher"] });
    },
  });
}

interface BatchCompletionEvent {
  batchId: string;
  status: string;
  failed: number;
  kind: string;
}

/** Mounted once in the Manager layout: fires `onCompletion` when an in-flight batch settles, on any page. */
export function useBatchCompletionWatcher(onCompletion: (e: BatchCompletionEvent) => void) {
  const known = useRef<Map<string, string>>(new Map());
  // After the first fetch, a batch we have never seen that is ALREADY settled
  // (small CSVs finish between two polls) is a completion too — otherwise the
  // toast and the employees/leaves refresh were silently skipped.
  const primed = useRef(false);
  const cb = useRef(onCompletion);
  useEffect(() => {
    cb.current = onCompletion;
  }, [onCompletion]);

  useQuery({
    queryKey: ["batches-watcher"],
    queryFn: async () => {
      const batches = await endpoints.batches();
      for (const b of batches) {
        const prev = known.current.get(b.id);
        const settledChange = prev !== undefined && prev !== b.status;
        const appearedSettled = prev === undefined && primed.current;
        if ((settledChange || appearedSettled) && !inFlight(b.status)) {
          cb.current({ batchId: b.id, status: b.status, failed: b.failed_files, kind: b.kind });
        }
        known.current.set(b.id, b.status);
      }
      primed.current = true;
      return batches;
    },
    refetchInterval: (query) => {
      return inFlightDelay((query.state.data as Batch[] | undefined) ?? []) || 15_000;
    },
  });
}

export function errorMessage(err: unknown): string {
  return err instanceof Error ? err.message : "Something went wrong";
}

export function useEmployeeCorrection() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (vars: { id: string; field: string; value: string }) =>
      api(`/employees/${vars.id}`, {
        method: "PATCH",
        body: JSON.stringify({ [vars.field]: vars.value }),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["employees"] }),
  });
}
