import { Link } from "react-router-dom";
import {
  AlertOctagon,
  ArrowRight,
  BarChart3,
  CalendarCheck2,
  FileSpreadsheet,
  Mail,
  PlayCircle,
  Users,
  UsersRound,
  type LucideIcon,
} from "lucide-react";
import { useApiQuery } from "../api/endpoints";
import { useAuth } from "../auth/AuthContext";
import { displayName } from "../lib/display";
import { Card, PageHeader, ReviewBadge, SectionTitle, Skeleton, Stat, StatusBadge } from "../components/ui/kit";
import { fmtDate } from "../lib/format";

interface Summary {
  role: string;
  scope: string;
  employees_total?: number;
  batches_total?: number;
  analysis_runs_completed?: number;
  violations_detected?: number;
  emails_sent?: number;
  employees_needing_review?: number;
  users_by_role?: Record<string, number>;
  latest_gets_batch?: { status: string; created_at: string } | null;
}

const ACTIONS: Record<string, { to: string; title: string; text: string; icon: LucideIcon }[]> = {
  MANAGER: [
    { to: "/gets", title: "Upload GETS sheets", text: "Screenshots in, verified hours out", icon: FileSpreadsheet },
    { to: "/leaves", title: "Update leave register", text: "Keep company leave in sync", icon: CalendarCheck2 },
    { to: "/employees", title: "Employee repository", text: "IDs, names and emails", icon: UsersRound },
  ],
  MASTER_ADMIN: [
    { to: "/users", title: "Manage users", text: "Create managers and executives", icon: Users },
    { to: "/all-uploads", title: "All GETS uploads", text: "Every manager's batches", icon: FileSpreadsheet },
    { to: "/analytics", title: "Analytics", text: "Trends across the organisation", icon: BarChart3 },
  ],
  EXECUTIVE: [
    { to: "/analytics", title: "Analytics", text: "Violations and trends", icon: BarChart3 },
    { to: "/all-reports", title: "All reports", text: "Every completed analysis", icon: PlayCircle },
    { to: "/directory", title: "Directory", text: "Managers and HR", icon: Users },
  ],
  HR: [
    { to: "/gets-sheets", title: "Monthly GETS sheets", text: "Your manager's uploads", icon: FileSpreadsheet },
    { to: "/leaves", title: "Leave register", text: "Company-side leave", icon: CalendarCheck2 },
    { to: "/employee-data", title: "Employee data", text: "Team master data", icon: UsersRound },
  ],
};

export function DashboardPage() {
  const { user } = useAuth();
  const { data, isLoading } = useApiQuery<Summary>(["summary"], "/dashboard/summary", {
    refetchInterval: 30_000,
  });
  if (isLoading || !data) return <Skeleton rows={6} />;

  const isHr = data.role === "HR";
  const exec = data.role === "MASTER_ADMIN" || data.role === "EXECUTIVE";
  const hour = new Date().getHours();
  const greeting = hour < 12 ? "Good morning" : hour < 18 ? "Good afternoon" : "Good evening";

  const cards: { label: string; value?: number; icon: LucideIcon; tone?: "primary" | "success" | "warning" | "danger" }[] = [
    { label: "Employees", value: data.employees_total, icon: UsersRound },
    { label: "Batches uploaded", value: data.batches_total, icon: FileSpreadsheet },
    ...(isHr
      ? []
      : [
          { label: "Analysis runs", value: data.analysis_runs_completed, icon: PlayCircle, tone: "success" as const },
          { label: "Violations detected", value: data.violations_detected, icon: AlertOctagon, tone: data.violations_detected ? ("danger" as const) : ("success" as const) },
          { label: "Emails sent", value: data.emails_sent, icon: Mail },
        ]),
  ];

  return (
    <div>
      <PageHeader
        eyebrow={`${greeting}${user ? `, ${displayName(user).split(" ")[0]}` : ""}`}
        title={isHr ? "Team Overview" : "Dashboard"}
        subtitle={`Scope: ${data.scope}`}
      />

      {Number(data.employees_needing_review) > 0 && (
        <div className="mb-6 flex flex-wrap items-center gap-3 rounded-2xl border border-warning-500/30 bg-warning-100 px-4 py-3">
          <ReviewBadge note={`${data.employees_needing_review} employee records were flagged during OCR extraction`} />
          <span className="text-sm text-warning-700">
            {data.employees_needing_review} record(s) need review before analysis accuracy is guaranteed.
          </span>
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-5">
        {cards.map((c) => (
          <div key={c.label} data-testid={`metric-${c.label}`}>
            <Stat label={c.label} value={c.value ?? "—"} icon={c.icon} tone={c.tone} />
          </div>
        ))}
      </div>

      <SectionTitle>Quick actions</SectionTitle>
      <div className="grid gap-4 md:grid-cols-3">
        {(ACTIONS[data.role] ?? []).map((a) => (
          <Link key={a.to} to={a.to} className="group">
            <Card className="flex items-center gap-4 p-5 transition group-hover:-translate-y-0.5 group-hover:border-primary-200 group-hover:shadow-pop">
              <span className="flex h-11 w-11 items-center justify-center rounded-xl bg-primary-50 text-primary-600">
                <a.icon className="h-5 w-5" />
              </span>
              <span className="flex-1">
                <span className="block text-sm font-semibold text-ink">{a.title}</span>
                <span className="block text-xs text-ink-3">{a.text}</span>
              </span>
              <ArrowRight className="h-4 w-4 text-ink-3 transition group-hover:translate-x-0.5 group-hover:text-primary-600" />
            </Card>
          </Link>
        ))}
      </div>

      {data.users_by_role && exec && (
        <>
          <SectionTitle>Active accounts by role</SectionTitle>
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
            {Object.entries(data.users_by_role).map(([role, n]) => (
              <Stat key={role} label={role.replace("_", " ")} value={n} />
            ))}
          </div>
        </>
      )}

      {isHr && data.latest_gets_batch && (
        <Card className="mt-6 flex items-center justify-between p-5">
          <div>
            <p className="text-sm text-ink-3">Latest GETS batch (your manager)</p>
            <p className="mt-1 font-medium text-ink" data-testid="hr-latest-batch">
              Status: {data.latest_gets_batch.status} · {fmtDate(data.latest_gets_batch.created_at)}
            </p>
          </div>
          <StatusBadge status={data.latest_gets_batch.status} />
        </Card>
      )}
    </div>
  );
}
