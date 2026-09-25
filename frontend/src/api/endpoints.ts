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
  processed_at?: string | null;
  sheet_status?: "VERIFIED" | "CORRECTED" | "NEEDS_REVIEW" | null;
  sheet_period?: string | null;
  sheet_employee?: string | null;
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
  started_at?: string;
  completed_at?: string | null;
  violations: Array<{
    employee_code: string;
    employee_name: string | null;
    violation_reason: string;
    customer_leave_value?: string | null;
    company_leave_value?: string | null;
    email_to: string | null;
    email_status: string;
    sent_at?: string | null;
    details?: {
      source?: string;
      periods?: string[];
      customer_leave_dates?: string[];
      missing_in_register?: string[];
    } | null;
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
  hr_accounts?: { id: string; email: string; full_name?: string | null; is_active: boolean }[];
  employee_count?: number;
  gets_batches_total?: number;
  gets_batches_completed?: number;
  gets_batches_recent?: {
    id: string; status: string; total_files: number; failed_files: number; created_at: string | null;
  }[];
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

export interface GetsCell {
  day: number;
  hours: number | null;
  status: string;
  raw: string;
  confidence: number;
  corrected: boolean;
}

export interface GetsLine {
  row_index: number;
  person_id: string;
  supplier: string;
  job_family: string;
  uom: string;
  project_id: string;
  sub_project: string;
  sub_project_id: string;
  remarks: string;
  cells: GetsCell[];
  printed_total: number | null;
  computed_total: number;
  confidence: number;
  issues: string[];
  is_out_of_office: boolean;
}

export interface GetsCheck {
  check: string;
  expected: unknown;
  actual: unknown;
  ok: boolean;
  mismatched_days?: number[];
}

export interface GetsSheet {
  employee_name: string;
  person_id: string;
  supplier: string;
  job_family: string;
  month: number | null;
  year: number | null;
  period: string | null;
  days_in_month: number;
  weekdays: string[];
  lines: GetsLine[];
  totals: Record<string, (number | null)[]>;
  totals_printed_total: Record<string, number | null>;
  checks: GetsCheck[];
  corrections: string[];
  warnings: string[];
  status: "VERIFIED" | "CORRECTED" | "NEEDS_REVIEW";
  verified: boolean;
  confidence: number;
}

interface FileExtraction {
  file: BatchFile;
  meta: { gets_sheets?: GetsSheet[] };
  rows: {
    id: number;
    row_index: number;
    data: Record<string, unknown> & { extra?: Record<string, unknown> };
    confidence: number | null;
    needs_review: boolean;
    review_note: string | null;
  }[];
}

interface LeaveEntry {
  id: number;
  employee_code: string;
  leave_date: string;
  leave_type: string | null;
  source: "UPLOAD" | "MANUAL" | string;
  batch_id: string | null;
  created_at: string | null;
}

export const endpoints = {
  fileExtraction: (batchId: string, fileId: string) =>
    api<FileExtraction>(`/uploads/batches/${batchId}/files/${fileId}/extraction`),
  leaves: (params: string) => api<{ items: LeaveEntry[]; total: number }>(`/leaves${params}`),
  addLeave: (body: { employee_code: string; start_date: string; end_date?: string; leave_type?: string }) =>
    api<{ inserted: number }>("/leaves", { method: "POST", body: JSON.stringify(body) }),
  deleteLeave: (id: number) => api(`/leaves/${id}`, { method: "DELETE" }),
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
