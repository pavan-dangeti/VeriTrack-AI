import { useQuery } from "@tanstack/react-query";
import { api } from "./client";

export interface BatchFile {
  id: string;
  original_filename: string;
  content_type_detected: string | null;
  file_size: number;
  status: string;
  error_message: string | null;
  rows_extracted: number | null;
  needs_review_count: number;
}

export interface Batch {
  id: string;
  manager_id?: string;
  manager_name?: string | null;
  manager_email?: string | null;
  kind: string;
  status: string;
  total_files: number;
  processed_files: number;
  failed_files: number;
  created_at: string;
  completed_at: string | null;
  files?: BatchFile[];
}

export interface Employee {
  id: string;
  manager_id: string;
  employee_code: string;
  full_name: string;
  official_email: string | null;
  personal_email: string | null;
  department: string | null;
  needs_review: boolean;
  review_note: string | null;
  ocr_confidence: number | null;
}

export interface RunDetail {
  run_id: string;
  batch_id: string;
  manager_id: string;
  status: string;
  totals: {
    files_processed: number;
    rows_processed: number;
    matched: number;
    violations: number;
    emails_sent: number;
    emails_missing: number;
    emails_errored: number;
    skipped: number;
  };
  violations: Array<{
    employee_code: string;
    employee_name: string | null;
    violation_reason: string;
    email_to: string | null;
    email_status: string;
  }>;
  skipped_rows: Array<{ employee_code?: string; status: string; reason?: string }>;
}

export interface UserProfile {
  id: string;
  email: string;
  full_name?: string | null;
  role: string;
  is_active: boolean;
  created_at: string | null;
  last_login_at: string | null;
  // MANAGER extras
  hr_accounts?: { id: string; email: string; full_name?: string | null; is_active: boolean }[];
  employee_count?: number;
  gets_batches_total?: number;
  gets_batches_completed?: number;
  gets_batches_recent?: {
    id: string; status: string; total_files: number; failed_files: number; created_at: string | null;
  }[];
  // HR extras
  manager?: { id: string; email: string; full_name?: string | null } | null;
}

export interface EmployeeDetail extends Employee {
  versions: {
    version: number; full_name: string; official_email: string | null;
    personal_email: string | null; department: string | null;
    change_source: string; created_at: string;
  }[];
  gets_batches: { id: string; status: string; total_files: number; created_at: string | null }[];
}

export const endpoints = {
  userProfile: (id: string) => api<UserProfile>(`/users/${id}/profile`),
  employeeDetail: (id: string) => api<EmployeeDetail>(`/employees/${id}/detail`),
  batches: (kind?: string) =>
    api<Batch[]>(`/uploads/batches${kind ? `?kind=${kind}` : ""}`),
  batch: (id: string) => api<Batch>(`/uploads/batches/${id}`),
  employees: () => api<{ items: Employee[]; total: number }>("/employees"),
  correctEmployee: (id: string, body: Record<string, string>) =>
    api(`/employees/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  analyze: (batchId: string) =>
    api(`/batches/${batchId}/analyze`, { method: "POST" }),
  analysis: (batchId: string) => api<RunDetail>(`/batches/${batchId}/analysis`),
  runsForBatches: (batchId: string) => api<RunDetail>(`/batches/${batchId}/analysis`),
  summary: () =>
    api<Record<string, unknown>>("/dashboard/summary"),
  audit: (params = "") =>
    api<{
      items: Array<{
        id: number;
        timestamp: string;
        action: string;
        result: string;
        actor_user_id: string | null;
        target_entity: string | null;
        ip_address: string | null;
      }>;
      total: number;
    }>(`/audit-logs${params}`),
};

export function useApiQuery<T>(key: unknown[], path: string, options = {}) {
  return useQuery<T>({
    queryKey: key,
    queryFn: () => api<T>(path),
    ...options,
  });
}
