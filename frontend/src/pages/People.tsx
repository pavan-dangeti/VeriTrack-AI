import { Link } from "react-router-dom";
import { useApiQuery } from "../api/endpoints";
import { displayName } from "../lib/display";
import { Card, PageHeader, Skeleton, StatusBadge } from "../components/ui/kit";

/** Executive-only read-only org view. */
export function DirectoryPage() {
  const { data, isLoading } = useApiQuery<{ items: { id: string; email: string; full_name?: string | null; role: string; is_active: boolean }[] }>(
    ["users-directory"],
    "/users",
  );
  if (isLoading) return <Skeleton rows={6} />;
  const people = (data?.items ?? []).filter((u) => u.role === "MANAGER" || u.role === "HR");
  return (
    <div>
      <PageHeader title="Manager & HR Directory" subtitle="Read-only organizational view." />
      <Card className="overflow-hidden">
        <table className="data-table">
          <thead>
            <tr>
              <th>Email</th>
              <th>Role</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {people.map((u) => (
              <tr key={u.id}>
                <td>
                  <Link to={`/people/${u.id}`} className="text-primary-600 hover:underline">
                    {displayName(u)}
                  </Link>
                  {u.full_name?.trim() && (
                    <span className="block text-xs text-gray-400">{u.email}</span>
                  )}
                </td>
                <td>{u.role}</td>
                <td><StatusBadge status={u.is_active ? "DONE" : "FAILED"} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </div>
  );
}

/** Manager: create HR accounts and see them listed. */
export function HrTeamPage() {
  const { data, isLoading } = useApiQuery<{ items: { id: string; email: string; full_name?: string | null; role: string; is_active: boolean }[] }>(
    ["users-hr"],
    "/users",
  );
  if (isLoading) return <Skeleton rows={4} />;
  const hrs = (data?.items ?? []).filter((u) => u.role === "HR");
  return (
    <div>
      <PageHeader
        title="My HR Team"
        subtitle="HR accounts you created. They can view and download your repository and GETS sheets."
      />
      <Card className="p-6">
        <h2 className="text-sm font-semibold text-gray-900">Create HR account</h2>
        <p className="mt-0.5 text-xs text-gray-500">
          HR accounts can view and download your repository and GETS sheets.
          The initial password is shown exactly once.
        </p>
        <HrCreateForm />
      </Card>
      <Card className="mt-4 overflow-hidden">
        <table className="data-table" data-testid="hr-team-table">
          <thead>
            <tr>
              <th>Email</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {hrs.length === 0 && (
              <tr><td colSpan={2} className="px-4 py-8 text-center text-sm text-gray-400">No HR accounts yet.</td></tr>
            )}
            {hrs.map((u) => (
              <tr key={u.id}>
                <td>
                  <Link to={`/people/${u.id}`} className="text-primary-600 hover:underline">
                    {displayName(u)}
                  </Link>
                  {u.full_name?.trim() && (
                    <span className="block text-xs text-gray-400">{u.email}</span>
                  )}
                </td>
                <td><StatusBadge status={u.is_active ? "DONE" : "FAILED"} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </div>
  );
}

import { useState } from "react";
import { Button, Input, PasswordModal } from "../components/ui/kit";
import { api } from "../api/client";
import { errorMessage } from "../api/hooks";
import { useQueryClient } from "@tanstack/react-query";
import { useToast } from "../components/ui/toast";

interface UserCreatedResponse {
  user: { email: string; role: string };
  initial_password: string;
}

function HrCreateForm() {
  const [email, setEmail] = useState("");
  const [fullName, setFullName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [passwordModal, setPasswordModal] = useState<{ password: string; email: string; role: string } | null>(null);
  const toast = useToast();
  const qc = useQueryClient();

  const submit = async () => {
    if (!email.includes("@")) return setError("Enter a valid email");
    setError(null);
    try {
      const resp = await api<UserCreatedResponse>("/users", { method: "POST", body: JSON.stringify({ email, role: "HR", full_name: fullName || null }) });
      setPasswordModal({ password: resp.initial_password, email: resp.user.email, role: resp.user.role });
      setEmail("");
      setFullName("");
      qc.invalidateQueries({ queryKey: ["users-hr"] });
    } catch (e) {
      toast("error", errorMessage(e));
    }
  };

  return (
    <>
      <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2">
        <Input label="Full name" value={fullName} onChange={(e) => setFullName(e.target.value)} placeholder="Sam Ortiz" />
        <Input label="HR email" value={email} onChange={(e) => setEmail(e.target.value)} error={error ?? undefined} placeholder="hr@corp.io" />
      </div>
      <div className="mt-4">
        <Button onClick={submit}>Create HR account</Button>
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
