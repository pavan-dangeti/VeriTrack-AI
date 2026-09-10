import { useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "./client";
import { endpoints, type Batch, type Employee } from "./endpoints";
export type { Employee } from "./endpoints";

export function useBatches(kind?: string) {
  return useQuery({
    queryKey: ["batches", kind],
    queryFn: () => endpoints.batches(kind),
    refetchInterval: (query) => {
      const data = query.state.data as Batch[] | undefined;
      const active = data?.some(
        (b) => b.status === "PROCESSING" || b.status === "QUEUED",
      );
      return active ? 2000 : false;
    },
  });
}

/** Polls one batch while any file is in-flight (real backend status only). */
export function useBatchDetail(batchId: string | null) {
  return useQuery({
    queryKey: ["batch", batchId],
    queryFn: () => endpoints.batch(batchId!),
    enabled: !!batchId,
    refetchInterval: (query) => {
      const d = query.state.data as Batch | undefined;
      const inflight = d?.files?.some(
        (f) => f.status === "QUEUED" || f.status === "PROCESSING",
      );
      return inflight ? 1500 : false;
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

export interface BatchCompletionEvent {
  batchId: string;
  status: string;
  failed: number;
}

/**
 * Mounted once in the layout for Managers: polls batch list and fires
 * `onCompletion` when a previously-in-flight batch settles — regardless of
 * which page the user is on (locked UX requirement 3b).
 */
export function useBatchCompletionWatcher(onCompletion: (e: BatchCompletionEvent) => void) {
  const known = useRef<Map<string, string>>(new Map());

  useQuery({
    queryKey: ["batches-watcher"],
    queryFn: async () => {
      const batches = await endpoints.batches();
      for (const b of batches) {
        const prev = known.current.get(b.id);
        if (prev && prev !== b.status && b.status !== "PROCESSING" && b.status !== "QUEUED") {
          onCompletion({ batchId: b.id, status: b.status, failed: b.failed_files });
        }
        known.current.set(b.id, b.status);
      }
      return batches;
    },
    refetchInterval: 4000,
    noRefetchOnMount: false,
  } as never);
}

export function errorMessage(err: unknown): string {
  return err instanceof Error ? err.message : "Something went wrong";
}

import { useMutation, useQueryClient } from "@tanstack/react-query";

/**
 * Inline-correction mutation for employee review flags.
 * Used by the Employee Repository grid's cell editor: PATCH creates a new
 * version server-side and clears the review flag (locked requirement 3a).
 */
export function useEmployeeCorrection() {
  const qc = useQueryClient();
  return {
    ...useMutation({
      mutationFn: async (vars: { id: string; field: string; value: string }) => {
        const body = { [vars.field]: vars.value };
        return api(`/employees/${vars.id}`, {
          method: "PATCH",
          body: JSON.stringify(body),
        });
      },
      onSuccess: () => {
        qc.invalidateQueries({ queryKey: ["employees"] });
      },
    }),
  };
}
