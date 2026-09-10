import type { ReactNode } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useApiQuery, type EmployeeDetail, type UserProfile } from "../api/endpoints";
import { useAuth } from "../auth/AuthContext";
import { displayName } from "../lib/display";
import {
  Card,
  EmptyState,
  PageHeader,
  ReviewBadge,
  SectionTitle,
  Skeleton,
  Stat,
  StatusBadge,
} from "../components/ui/kit";

const ROLE_LABEL: Record<string, string> = {
  MASTER_ADMIN: "Master Admin",
  EXECUTIVE: "Executive",
  MANAGER: "Manager",
  HR: "HR",
};

function fmt(iso: string | null | undefined): string {
  return iso ? new Date(iso).toLocaleString() : "—";
}

function BackButton() {
  const navigate = useNavigate();
  return (
    <button
      onClick={() => navigate(-1)}
      data-testid="back-button"
      className="mb-2 inline-flex items-center gap-1 text-sm text-primary-600 hover:text-primary-700"
    >
      ← Back
    </button>
  );
}

function Field({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="px-4 py-3">
      <dt className="text-xs uppercase tracking-wide text-gray-400">{label}</dt>
      <dd className="mt-0.5 text-sm text-gray-900">{value}</dd>
    </div>
  );
}

function ManagerExtras({ profile }: { profile: UserProfile }) {
  const hrs = profile.hr_accounts ?? [];
  return (
    <>
      <div className="mt-4 grid grid-cols-3 gap-3">
        <Stat label="HR accounts" value={profile.hr_accounts?.length ?? 0} />
        <Stat label="Employees in repository" value={profile.employee_count ?? 0} />
        <Stat
          label="GETS batches processed"
          value={`${profile.gets_batches_completed ?? 0} / ${profile.gets_batches_total ?? 0}`}
        />
      </div>

      <SectionTitle>HR team</SectionTitle>
      <Card className="overflow-hidden">
        <table className="data-table" data-testid="profile-hr-table">
          <tbody>
            {hrs.length === 0 && (
              <tr><td className="px-4 py-6 text-center text-sm text-gray-400">No HR accounts yet.</td></tr>
            )}
            {hrs.map((h) => (
              <tr key={h.id}>
                <td>
                  <Link to={`/people/${h.id}`} className="text-primary-600 hover:underline">
                    {displayName(h)}
                  </Link>
                  {h.full_name?.trim() && (
                    <span className="block text-xs text-gray-400">{h.email}</span>
                  )}
                </td>
                <td className="text-right">
                  <StatusBadge status={h.is_active ? "DONE" : "FAILED"} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>

      <SectionTitle>GETS batch history</SectionTitle>
      <Card className="overflow-hidden">
        <table className="data-table" data-testid="profile-batches-table">
          <thead>
            <tr>
              <th>Uploaded</th>
              <th>Files</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {(profile.gets_batches_recent ?? []).length === 0 && (
              <tr><td colSpan={3} className="px-4 py-6 text-center text-sm text-gray-400">No GETS batches yet.</td></tr>
            )}
            {(profile.gets_batches_recent ?? []).map((b) => (
              <tr key={b.id}>
                <td>{fmt(b.created_at)}</td>
                <td>{b.total_files}</td>
                <td><StatusBadge status={b.status} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </>
  );
}

function HrManagerField({ profile, linkable }: { profile: UserProfile; linkable: boolean }) {
  if (!profile.manager) return null;
  return (
    <Field
      label="Reports to"
      value={
        linkable ? (
          <Link to={`/people/${profile.manager.id}`} className="text-primary-600 hover:underline">
            {displayName(profile.manager)}
          </Link>
        ) : (
          displayName(profile.manager)
        )
      }
    />
  );
}

export function UserProfilePage() {
  const { userId } = useParams();
  if (!userId) return null;
  return <UserProfilePageInner id={userId} />;
}

export function MyProfilePage() {
  const { user } = useAuth();
  if (!user) return null;
  return <UserProfilePageInner id={user.id} hideBack />;
}

/** Shared body: /profile (self, no back button) and /people/:userId both use it. */
function UserProfilePageInner({ id, hideBack = false }: { id: string; hideBack?: boolean }) {
  const { user } = useAuth();
  const { data, isLoading, isError } = useApiQuery<UserProfile>(
    ["user-profile", id],
    `/users/${id}/profile`,
  );
  if (!user) return null;
  if (isLoading) return <Skeleton rows={5} />;
  if (isError || !data) {
    return (
      <div>
        {!hideBack && <BackButton />}
        <Card><EmptyState title="Profile unavailable" hint="This account is outside your scope or no longer exists." /></Card>
      </div>
    );
  }
  const canDrill = user.role !== "HR";
  return (
    <div data-testid="user-profile-page">
      {!hideBack && <BackButton />}
      <PageHeader
        title={displayName(data)}
        subtitle={`${ROLE_LABEL[data.role] ?? data.role} profile${data.full_name?.trim() ? ` · ${data.email}` : ""}`}
      />
      <Card>
        <dl className="grid grid-cols-2 divide-x divide-y divide-gray-100 sm:grid-cols-3">
          {data.full_name?.trim() && <Field label="Name" value={data.full_name} />}
          <Field label="Email" value={data.email} />
          <Field label="Role" value={ROLE_LABEL[data.role] ?? data.role} />
          <Field label="Status" value={<StatusBadge status={data.is_active ? "DONE" : "FAILED"} />} />
          <Field label="Account created" value={fmt(data.created_at)} />
          <Field label="Last login" value={fmt(data.last_login_at)} />
          {data.role === "HR" && <HrManagerField profile={data} linkable={canDrill} />}
        </dl>
      </Card>
      {data.role === "MANAGER" && <ManagerExtras profile={data} />}
    </div>
  );
}

export function EmployeeDetailPage() {
  const { employeeId } = useParams();
  const { data, isLoading, isError } = useApiQuery<EmployeeDetail>(
    ["employee-detail", employeeId],
    `/employees/${employeeId}/detail`,
  );
  if (isLoading) return <Skeleton rows={5} />;
  if (isError || !data) {
    return (
      <div>
        <BackButton />
        <Card><EmptyState title="Employee unavailable" hint="This record is outside your scope or no longer exists." /></Card>
      </div>
    );
  }
  return (
    <div data-testid="employee-detail-page">
      <BackButton />
      <PageHeader
        title={`${data.full_name}`}
        subtitle={`Employee ${data.employee_code}`}
        actions={data.needs_review ? <ReviewBadge note={data.review_note} /> : undefined}
      />
      <Card>
        <dl className="grid grid-cols-2 divide-x divide-y divide-gray-100 sm:grid-cols-3">
          <Field label="Employee ID" value={data.employee_code} />
          <Field label="Full name" value={data.full_name} />
          <Field label="Department" value={data.department ?? "—"} />
          <Field label="Official email" value={data.official_email ?? "—"} />
          <Field label="Personal email" value={data.personal_email ?? "—"} />
        </dl>
      </Card>

      <SectionTitle>Edit history</SectionTitle>
      <Card className="overflow-hidden">
        <table className="data-table" data-testid="employee-versions-table">
          <thead>
            <tr>
              <th>Version</th>
              <th>Name</th>
              <th>Source</th>
              <th>When</th>
            </tr>
          </thead>
          <tbody>
            {data.versions.map((v) => (
              <tr key={v.version}>
                <td>v{v.version}</td>
                <td>{v.full_name}</td>
                <td>{v.change_source}</td>
                <td>{fmt(v.created_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>

      <SectionTitle>Appeared in GETS batches</SectionTitle>
      <Card className="overflow-hidden">
        <table className="data-table" data-testid="employee-batches-table">
          <tbody>
            {data.gets_batches.length === 0 && (
              <tr><td className="px-4 py-6 text-center text-sm text-gray-400">No GETS batches contain this employee yet.</td></tr>
            )}
            {data.gets_batches.map((b) => (
              <tr key={b.id}>
                <td>{fmt(b.created_at)}</td>
                <td>{b.total_files} file(s)</td>
                <td><StatusBadge status={b.status} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </div>
  );
}
