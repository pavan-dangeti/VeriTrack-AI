import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CalendarCheck2, CalendarPlus, Search, Trash2 } from "lucide-react";
import { endpoints } from "../api/endpoints";
import { errorMessage, useUploadBatch } from "../api/hooks";
import { useAuth } from "../auth/AuthContext";
import {
  Badge,
  Button,
  Card,
  Dropzone,
  EmptyState,
  Input,
  Modal,
  PageHeader,
  Skeleton,
} from "../components/ui/kit";
import { useToast } from "../components/ui/toast";
import { fmtDate, fmtPeriod } from "../lib/format";

function currentMonth() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

export function LeaveRegisterPage() {
  const { user } = useAuth();
  const canEdit = user?.role === "MANAGER";
  const toast = useToast();
  const qc = useQueryClient();
  const [month, setMonth] = useState(currentMonth());
  const [code, setCode] = useState("");
  const [adding, setAdding] = useState(false);

  const params = useMemo(() => {
    const p = new URLSearchParams({ limit: "500" });
    if (month) p.set("month", month);
    if (code.trim()) p.set("employee_code", code.trim());
    return `?${p}`;
  }, [month, code]);

  const { data, isLoading } = useQuery({
    queryKey: ["leaves", params],
    queryFn: () => endpoints.leaves(params),
    placeholderData: (prev) => prev,
  });

  const uploadMut = useUploadBatch("COMPANY_LEAVE");
  const remove = useMutation({
    mutationFn: (id: number) => endpoints.deleteLeave(id),
    onSuccess: () => {
      toast("success", "Leave entry removed");
      qc.invalidateQueries({ queryKey: ["leaves"] });
    },
    onError: (e) => toast("error", errorMessage(e)),
  });

  const byEmployee = useMemo(() => {
    const m = new Map<string, number>();
    data?.items.forEach((l) => m.set(l.employee_code, (m.get(l.employee_code) ?? 0) + 1));
    return m;
  }, [data]);

  return (
    <div>
      <PageHeader
        eyebrow="Workspace"
        title="Company Leave Register"
        subtitle="Company-side leave records. Every GETS 'Out Of Office' day must have a matching entry here, or analysis flags it."
        actions={canEdit && <Button icon={CalendarPlus} onClick={() => setAdding(true)} data-testid="add-leave">Add leave</Button>}
      />

      {canEdit && (
        <div className="mb-6">
          <Dropzone
            accept={["csv", "xlsx", "xls"]}
            busy={uploadMut.isPending}
            testId="leave-file-input"
            title="Import a leave register (CSV / Excel)"
            hint="Columns: Employee ID + Date — or From Date / To Date ranges. Optional: Leave Type. Re-imports never duplicate."
            onFiles={(files) =>
              uploadMut.mutate(files, {
                onSuccess: () => toast("info", "Register queued — entries appear as soon as it is processed"),
                onError: (e) => toast("error", errorMessage(e)),
              })
            }
          />
        </div>
      )}

      <Card className="mb-4 flex flex-col gap-3 p-4 sm:flex-row sm:items-end">
        <div className="sm:w-48">
          <Input label="Month" type="month" value={month} onChange={(e) => setMonth(e.target.value)} data-testid="leave-month" />
        </div>
        <div className="relative sm:w-64">
          <Input label="Employee ID" placeholder="e.g. 100001" value={code} onChange={(e) => setCode(e.target.value)} />
          <Search className="pointer-events-none absolute right-3 top-[38px] h-4 w-4 text-ink-3" aria-hidden />
        </div>
        <div className="flex flex-wrap gap-2 sm:ml-auto">
          <Badge tone="primary">{data?.total ?? 0} day(s)</Badge>
          <Badge>{byEmployee.size} employee(s)</Badge>
          {month && <Badge>{fmtPeriod(month)}</Badge>}
        </div>
      </Card>

      <Card className="overflow-x-auto">
        {isLoading ? (
          <Skeleton rows={5} />
        ) : !data?.items.length ? (
          <EmptyState icon={CalendarCheck2} title="No leave recorded for this filter" hint={canEdit ? "Import your register or add entries manually." : undefined} />
        ) : (
          <table className="data-table" data-testid="leaves-table">
            <thead>
              <tr>
                <th>Employee ID</th>
                <th>Date</th>
                <th>Type</th>
                <th>Source</th>
                {canEdit && <th className="text-right">Actions</th>}
              </tr>
            </thead>
            <tbody>
              {data.items.map((l) => (
                <tr key={l.id}>
                  <td className="font-mono text-ink">{l.employee_code}</td>
                  <td>{fmtDate(l.leave_date, { weekday: "short" })}</td>
                  <td>{l.leave_type ?? <span className="text-ink-3">—</span>}</td>
                  <td><Badge tone={l.source === "UPLOAD" ? "primary" : "neutral"}>{l.source === "UPLOAD" ? "Imported" : "Manual"}</Badge></td>
                  {canEdit && (
                    <td className="text-right">
                      <Button
                        variant="ghost"
                        size="sm"
                        icon={Trash2}
                        aria-label={`Delete leave ${l.leave_date} for ${l.employee_code}`}
                        loading={remove.isPending && remove.variables === l.id}
                        onClick={() => remove.mutate(l.id)}
                      />
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>

      {canEdit && <AddLeaveModal open={adding} onClose={() => setAdding(false)} />}
    </div>
  );
}

function AddLeaveModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const toast = useToast();
  const qc = useQueryClient();
  const [form, setForm] = useState({ employee_code: "", start_date: "", end_date: "", leave_type: "" });
  const add = useMutation({
    mutationFn: () =>
      endpoints.addLeave({
        employee_code: form.employee_code.trim(),
        start_date: form.start_date,
        end_date: form.end_date || undefined,
        leave_type: form.leave_type.trim() || undefined,
      }),
    onSuccess: (r) => {
      toast("success", r.inserted ? `${r.inserted} leave day(s) added` : "Those days were already recorded");
      qc.invalidateQueries({ queryKey: ["leaves"] });
      setForm({ employee_code: "", start_date: "", end_date: "", leave_type: "" });
      onClose();
    },
    onError: (e) => toast("error", errorMessage(e)),
  });
  const valid = form.employee_code.trim().length >= 3 && form.start_date;
  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Add company leave"
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>Cancel</Button>
          <Button onClick={() => add.mutate()} disabled={!valid} loading={add.isPending} data-testid="save-leave">Save</Button>
        </>
      }
    >
      <form
        className="grid gap-4 sm:grid-cols-2"
        onSubmit={(e) => {
          e.preventDefault();
          if (valid) add.mutate();
        }}
      >
        <div className="sm:col-span-2">
          <Input label="Employee ID" value={form.employee_code} onChange={(e) => setForm({ ...form, employee_code: e.target.value })} placeholder="100001" required />
        </div>
        <Input label="From" type="date" value={form.start_date} onChange={(e) => setForm({ ...form, start_date: e.target.value })} required />
        <Input label="To (optional)" type="date" value={form.end_date} min={form.start_date} onChange={(e) => setForm({ ...form, end_date: e.target.value })} />
        <div className="sm:col-span-2">
          <Input label="Leave type (optional)" value={form.leave_type} onChange={(e) => setForm({ ...form, leave_type: e.target.value })} placeholder="Casual, Sick, Earned…" />
        </div>
      </form>
    </Modal>
  );
}
