import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { useApiQuery } from "../api/endpoints";
import { Card, EmptyState, PageHeader, SectionTitle, Skeleton } from "../components/ui/kit";
import { useAuth } from "../auth/AuthContext";

interface MonthPoint {
  month: string;
  violations: number;
  rows_processed: number;
  matched: number;
  batches: number;
  files_processed: number;
}

interface AnalyticsSummary {
  scoped_to_self: boolean;
  monthly: MonthPoint[];
  emails: { sent: number; missing: number; errored: number; skipped: number };
  by_manager?: {
    manager_id: string;
    manager_name: string;
    manager_email: string;
    violations: number;
    runs: number;
    batches: number;
  }[];
}

const MONTH_FMT = (m: string) =>
  new Date(`${m}-02T00:00:00Z`).toLocaleString(undefined, { month: "short", year: "2-digit" });

const EMAIL_COLORS = ["#16a34a", "#d97706", "#dc2626", "#6b7280"];

function ChartCard({ title, subtitle, children }: { title: string; subtitle?: string; children: React.ReactNode }) {
  return (
    <Card className="p-5">
      <h2 className="text-sm font-semibold uppercase tracking-wide text-gray-400">{title}</h2>
      {subtitle && <p className="mt-0.5 text-xs text-gray-400">{subtitle}</p>}
      <div className="mt-4 h-64">{children}</div>
    </Card>
  );
}

export function AnalyticsPage() {
  const { user } = useAuth();
  const { data, isLoading } = useApiQuery<AnalyticsSummary>(["analytics"], "/analytics/summary");

  if (isLoading) return <Skeleton rows={8} />;
  const monthly = data?.monthly ?? [];
  const emails = data?.emails ?? { sent: 0, missing: 0, errored: 0, skipped: 0 };
  const emailSeries = [
    { name: "Sent", value: emails.sent },
    { name: "Missing email", value: emails.missing },
    { name: "Errored", value: emails.errored },
    { name: "Skipped", value: emails.skipped },
  ];
  const anyEmail = emailSeries.some((e) => e.value > 0);
  const isAdminView = user?.role === "MASTER_ADMIN" || user?.role === "EXECUTIVE";
  const isHr = user?.role === "HR";
  const scopeLabel = isAdminView
    ? "System-wide, all managers."
    : isHr
      ? "Your manager's workspace."
      : "Your workspace only.";

  return (
    <div data-testid="analytics-page">
      <PageHeader title="Analytics" subtitle={scopeLabel} />

      {monthly.length === 0 ? (
        <Card>
          <EmptyState
            title="No analytics yet"
            hint="Metrics appear once GETS batches have been uploaded and analyzed."
          />
        </Card>
      ) : (
        <div className="grid grid-cols-1 gap-5 xl:grid-cols-2">
          <ChartCard title="Violations over time" subtitle="Per month of analysis run">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={monthly}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
                <XAxis dataKey="month" tickFormatter={MONTH_FMT} fontSize={12} />
                <YAxis allowDecimals={false} fontSize={12} />
                <Tooltip />
                <Line type="monotone" dataKey="violations" stroke="#dc2626" strokeWidth={2} dot={{ r: 3 }} />
              </LineChart>
            </ResponsiveContainer>
          </ChartCard>

          <ChartCard title="Processed vs matched" subtitle="Employee rows per month">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={monthly}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
                <XAxis dataKey="month" tickFormatter={MONTH_FMT} fontSize={12} />
                <YAxis allowDecimals={false} fontSize={12} />
                <Tooltip />
                <Legend />
                <Bar dataKey="rows_processed" name="Processed" fill="#2563eb" radius={[3, 3, 0, 0]} />
                <Bar dataKey="matched" name="Matched" fill="#16a34a" radius={[3, 3, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </ChartCard>

          <ChartCard title="Email outcomes" subtitle="Notifications per analysis run, all time">
            {anyEmail ? (
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie
                    data={emailSeries}
                    dataKey="value"
                    nameKey="name"
                    innerRadius={55}
                    outerRadius={85}
                    paddingAngle={2}
                  >
                    {emailSeries.map((_, i) => (
                      <Cell key={i} fill={EMAIL_COLORS[i]} />
                    ))}
                  </Pie>
                  <Tooltip />
                  <Legend />
                </PieChart>
              </ResponsiveContainer>
            ) : (
              <EmptyState title="No emails yet" hint="Email outcomes show up after violation analysis runs." />
            )}
          </ChartCard>

          <ChartCard title="Upload volume" subtitle="Files processed per month">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={monthly}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
                <XAxis dataKey="month" tickFormatter={MONTH_FMT} fontSize={12} />
                <YAxis allowDecimals={false} fontSize={12} />
                <Tooltip />
                <Bar dataKey="files_processed" name="Files" fill="#7c3aed" radius={[3, 3, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </ChartCard>
        </div>
      )}

      {isAdminView && (data?.by_manager?.length ?? 0) > 0 && (
        <div className="mt-2">
          <SectionTitle>By manager</SectionTitle>
          <div className="grid grid-cols-1 gap-5 xl:grid-cols-2">
            <ChartCard title="Violations per manager" subtitle="Total violations by uploader">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={data!.by_manager!} layout="vertical" margin={{ left: 8 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
                  <XAxis type="number" allowDecimals={false} fontSize={12} />
                  <YAxis
                    type="category"
                    dataKey="manager_name"
                    width={140}
                    tickFormatter={(v: string) => (v.length > 18 ? v.slice(0, 18) + "…" : v)}
                    fontSize={12}
                  />
                  <Tooltip />
                  <Bar dataKey="violations" name="Violations" fill="#dc2626" radius={[0, 3, 3, 0]} />
                  <Bar dataKey="batches" name="Batches" fill="#7c3aed" radius={[0, 3, 3, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </ChartCard>
            <Card className="overflow-hidden">
              <table className="data-table" data-testid="by-manager-table">
                <thead>
                  <tr>
                    <th>Manager</th>
                    <th>Analysis runs</th>
                    <th>Violations</th>
                    <th>Batches uploaded</th>
                  </tr>
                </thead>
                <tbody>
                  {data!.by_manager!.map((m) => (
                    <tr key={m.manager_id}>
                      <td>
                        {m.manager_name}
                        {m.manager_name !== m.manager_email && (
                          <span className="block text-xs text-gray-400">{m.manager_email}</span>
                        )}
                      </td>
                      <td>{m.runs}</td>
                      <td className="font-medium text-gray-900">{m.violations}</td>
                      <td>{m.batches}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Card>
          </div>
        </div>
      )}
    </div>
  );
}
