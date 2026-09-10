import { useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { useApiQuery } from "../api/endpoints";
import { errorMessage } from "../api/hooks";
import { displayName } from "../lib/display";
import { Button, Card, Input, PageHeader, Skeleton, StatusBadge, PasswordModal } from "../components/ui/kit";
import { useToast } from "../components/ui/toast";

interface ManagedUser {
  id: string;
  email: string;
  full_name?: string | null;
  role: string;
  is_active: boolean;
}

interface UserCreatedResponse {
  user: ManagedUser;
  initial_password: string;
}

export function ManageUsersPage() {
  const qc = useQueryClient();
  const toast = useToast();
  const usersQ = useApiQuery<{ items: ManagedUser[]; total: number }>(["users"], "/users");
  const domainsQ = useApiQuery<{ items: { domain: string; is_active: boolean }[] }>(
    ["domains"],
    "/settings/m365-domains",
  );

  const [email, setEmail] = useState("");
  const [fullName, setFullName] = useState("");
  const [role, setRole] = useState("MANAGER");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [passwordModal, setPasswordModal] = useState<{ password: string; email: string; role: string } | null>(null);

  const submit = async () => {
    const errs: Record<string, string> = {};
    if (!email.includes("@")) errs.email = "Enter a valid email";
    if (!["MANAGER", "EXECUTIVE"].includes(role)) errs.role = "Role must be Manager or Executive";
    setErrors(errs);
    if (Object.keys(errs).length) return;
    try {
      const resp = await api<UserCreatedResponse>("/users", {
        method: "POST",
        body: JSON.stringify({ email, role, full_name: fullName || null }),
      });
      setPasswordModal({ password: resp.initial_password, email: resp.user.email, role: resp.user.role });
      setEmail("");
      setFullName("");
      qc.invalidateQueries({ queryKey: ["users"] });
    } catch (e) {
      toast("error", errorMessage(e));
    }
  };

  const toggle = useMutation({
    mutationFn: (u: ManagedUser) =>
      api(`/users/${u.id}/status`, {
        method: "PATCH",
        body: JSON.stringify({ is_active: !u.is_active }),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["users"] }),
    onError: (e) => toast("error", errorMessage(e)),
  });

  const approveDomain = useMutation({
    mutationFn: (domain: string) =>
      api("/settings/m365-domains", { method: "POST", body: JSON.stringify({ domain }) }),
    onSuccess: () => {
      toast("success", "Domain approved for M365 SSO");
      qc.invalidateQueries({ queryKey: ["domains"] });
    },
    onError: (e) => toast("error", errorMessage(e)),
  });

  if (usersQ.isLoading) return <Skeleton rows={6} />;

  return (
    <>
      <div className="space-y-8">
        <div>
          <PageHeader
            title="Manage Users"
            subtitle="Create Manager/Executive accounts, disable or restore access."
          />
          <Card className="mb-6 p-6">
            <h2 className="text-sm font-semibold text-gray-900">Create account</h2>
            <p className="mt-0.5 text-xs text-gray-500">
              Provision a Manager or Executive. The initial password is generated and
              shown exactly once.
            </p>
            <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2">
              <Input label="Full name" value={fullName} onChange={(e) => setFullName(e.target.value)} placeholder="Priya Nair" />
              <Input label="Email" value={email} onChange={(e) => setEmail(e.target.value)} error={errors.email} placeholder="new.manager@corp.io" />
            </div>
            <div className="mt-4 flex flex-wrap items-end gap-4">
              <label className="block">
                <span className="mb-1 block text-sm font-medium text-gray-700">Role</span>
                <select
                  value={role}
                  onChange={(e) => setRole(e.target.value)}
                  className="w-48 rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-primary-500 focus:outline-none focus:ring-2 focus:ring-primary-100"
                >
                  <option>MANAGER</option>
                  <option>EXECUTIVE</option>
                </select>
                {errors.role && <span className="mt-1 block text-xs text-danger-700">{errors.role}</span>}
              </label>
              <Button onClick={submit} data-testid="create-user">Create account</Button>
            </div>
          </Card>

          <Card className="overflow-hidden">
            <table className="data-table" data-testid="users-table">
              <thead>
                <tr>
                  <th>Email</th>
                  <th>Role</th>
                  <th>Status</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {(usersQ.data?.items ?? []).map((u) => (
                  <tr key={u.id}>
                    <td>
                      {["MANAGER", "HR"].includes(u.role) ? (
                        <Link to={`/people/${u.id}`} className="text-primary-600 hover:underline">
                          {displayName(u)}
                        </Link>
                      ) : (
                        displayName(u)
                      )}
                      {u.full_name?.trim() && (
                        <span className="block text-xs text-gray-400">{u.email}</span>
                      )}
                    </td>
                    <td>{u.role.replace("_", " ")}</td>
                    <td>
                      <StatusBadge status={u.is_active ? "DONE" : "FAILED"} />
                      <span className="ml-2 text-gray-500">{u.is_active ? "Active" : "Disabled"}</span>
                    </td>
                    <td className="text-right">
                      {!u.email.endsWith("@veritrack.io") || u.role !== "MASTER_ADMIN" ? (
                        <Button variant={u.is_active ? "danger" : "primary"} className="!px-2 !py-1 !text-xs"
                          onClick={() => toggle.mutate(u)}>
                          {u.is_active ? "Disable" : "Enable"}
                        </Button>
                      ) : null}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        </div>

        <div>
          <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-gray-400">
            Approved M365 SSO domains
          </h2>
          <DomainManager domains={domainsQ.data?.items ?? []} onApprove={(d) => approveDomain.mutate(d)} />
        </div>
      </div>
      <PasswordModal
        isOpen={!!passwordModal}
        onClose={() => setPasswordModal(null)}
        password={passwordModal?.password ?? ""}
        email={passwordModal?.email ?? ""}
        role={passwordModal?.role ?? ""}
      />
    </>
  );
}

function DomainManager({
  domains,
  onApprove,
}: {
  domains: { domain: string; is_active: boolean }[];
  onApprove: (d: string) => void;
}) {
  const [domain, setDomain] = useState("");
  return (
    <Card className="p-4">
      <div className="mb-3 flex gap-2">
        <input
          value={domain}
          onChange={(e) => setDomain(e.target.value)}
          placeholder="corp.io"
          className="w-56 rounded-lg border border-gray-300 px-3 py-2 text-sm"
        />
        <Button onClick={() => { onApprove(domain); setDomain(""); }}>Approve domain</Button>
      </div>
      {domains.length === 0 ? (
        <p className="text-sm text-gray-400">No domains approved yet — SSO logins will be denied.</p>
      ) : (
        <div className="flex flex-wrap gap-2">
          {domains.map((d) => (
            <span key={d.domain} className={`rounded-full px-3 py-1 text-sm ${d.is_active ? "bg-success-100 text-success-700" : "bg-gray-100 text-gray-500"}`}>
              {d.domain}
            </span>
          ))}
        </div>
      )}
    </Card>
  );
}
