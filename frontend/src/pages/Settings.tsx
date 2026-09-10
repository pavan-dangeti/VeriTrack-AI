import { useState } from "react";
import { api } from "../api/client";
import { useApiQuery } from "../api/endpoints";
import { useAuth } from "../auth/AuthContext";
import { errorMessage } from "../api/hooks";
import { Button, Card, PageHeader } from "../components/ui/kit";
import { useToast } from "../components/ui/toast";

function RetentionCard() {
  const { data } = useApiQuery<{ retention_days: number }>(["settings"], "/settings");
  const toast = useToast();
  const [busy, setBusy] = useState(false);

  const purge = async () => {
    if (!window.confirm(
      `Permanently delete all GETS batches and reports older than ${data?.retention_days ?? "?"} days? Employee records are not affected.`,
    )) {
      return;
    }
    setBusy(true);
    try {
      const r = await api<{ purged_batches: number }>("/settings/purge-obsolete-data", { method: "POST" });
      toast("success", `Purged ${r.purged_batches} obsolete batch(es).`);
    } catch (e) {
      toast("error", errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card className="p-5">
      <h3 className="font-medium">Retention policy</h3>
      <p className="mt-1 text-sm text-gray-500">
        GETS batches and generated reports become purgeable after{" "}
        <strong>{data?.retention_days ?? "…"} days</strong> (RETENTION_DAYS env var).
        Employee repository records are versioned and soft-delete only — they are never
        purged by this action.
      </p>
      <div className="mt-3">
        <Button variant="danger" onClick={purge} disabled={busy} data-testid="purge-button">
          Purge obsolete data now
        </Button>
      </div>
    </Card>
  );
}

export function AccountSettingsPage() {
  const { user } = useAuth();
  return (
    <div>
      <PageHeader title="Account Settings" subtitle="Your identity and session information." />
      <Card className="max-w-lg p-6">
        <dl className="space-y-3 text-sm">
          <div className="flex justify-between">
            <dt className="text-gray-500">Email</dt>
            <dd className="font-medium">{user?.email}</dd>
          </div>
          <div className="flex justify-between">
            <dt className="text-gray-500">Role</dt>
            <dd className="font-medium">{user?.role.replace("_", " ")}</dd>
          </div>
          <div className="flex justify-between">
            <dt className="text-gray-500">Sessions</dt>
            <dd className="font-medium">Refresh-token rotation active</dd>
          </div>
        </dl>
      </Card>
    </div>
  );
}

export function SystemSettingsPage() {
  return (
    <div>
      <PageHeader
        title="System Settings"
        subtitle="Platform-wide configuration (Master Admin only)."
      />
      <div className="max-w-2xl space-y-4">
        <Card className="p-5">
          <h3 className="font-medium">M365 SSO domains</h3>
          <p className="mt-1 text-sm text-gray-500">
            Managed under Manage Users → Approved M365 SSO domains. Only emails whose
            domain is on the allowlist may sign in via Microsoft Entra ID.
          </p>
        </Card>
        <Card className="p-5">
          <h3 className="font-medium">Email templates</h3>
          <p className="mt-1 text-sm text-gray-500">
            Violation notices currently use the system template. Custom templates arrive
            with the Graph live-mode integration.
          </p>
        </Card>
        <RetentionCard />
      </div>
    </div>
  );
}
