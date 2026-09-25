import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  AlertTriangle,
  ArrowLeft,
  CheckCircle2,
  Columns2,
  Image as ImageIcon,
  Sparkles,
  Table2,
  XCircle,
} from "lucide-react";
import { blobUrl } from "../api/client";
import { endpoints, type GetsLine, type GetsSheet } from "../api/endpoints";
import { Badge, Card, EmptyState, PageHeader, SectionTitle, Skeleton, StatusBadge, Tabs } from "../components/ui/kit";
import { fmtHours, fmtPeriod } from "../lib/format";

const CELL_STYLE: Record<string, string> = {
  USER_SIGNED: "bg-gets-signed text-white",
  PM_APPROVED: "bg-gets-pm text-slate-900 ring-1 ring-inset ring-amber-300/70",
  LM_APPROVED: "bg-gets-lm text-slate-900",
  PLANNED: "bg-gets-planned text-white",
  FILLED: "bg-primary-100 text-primary-900",
};

const LEGEND = [
  { key: "PLANNED", label: "Planned" },
  { key: "USER_SIGNED", label: "User signed" },
  { key: "PM_APPROVED", label: "PM approved" },
  { key: "LM_APPROVED", label: "LM approved" },
];

export function SheetReviewPage() {
  const { batchId = "", fileId = "" } = useParams();
  const { data, isLoading, error } = useQuery({
    queryKey: ["extraction", batchId, fileId],
    queryFn: () => endpoints.fileExtraction(batchId, fileId),
    staleTime: 60_000,
  });
  const [view, setView] = useState<"split" | "grid" | "image">("split");
  const navigate = useNavigate();

  if (isLoading) return <Skeleton rows={8} />;
  if (error || !data) {
    return (
      <Card>
        <EmptyState title="Extraction not available" hint={(error as Error)?.message} />
      </Card>
    );
  }
  const sheets = data.meta.gets_sheets ?? [];

  return (
    <div data-testid="sheet-review-page">
      <button onClick={() => navigate(-1)} className="mb-4 inline-flex items-center gap-1.5 text-sm text-ink-2 hover:text-ink" data-testid="back-button">
        <ArrowLeft className="h-4 w-4" /> Back
      </button>
      <PageHeader
        eyebrow="Extraction review"
        title={data.file.original_filename}
        subtitle={
          sheets.length
            ? "Every value below was read from the screenshot and reconciled against the sheet's own row and day totals."
            : `${data.rows.length} rows extracted.`
        }
        actions={
          sheets.length > 0 && (
            <Tabs
              value={view}
              onChange={setView}
              tabs={[
                { id: "split", label: "Side by side" },
                { id: "grid", label: "Grid" },
                { id: "image", label: "Original" },
              ]}
            />
          )
        }
      />
      {sheets.length === 0 ? (
        <GenericRows rows={data.rows} />
      ) : (
        sheets.map((sheet, i) => (
          <SheetView key={i} sheet={sheet} view={view} batchId={batchId} fileId={fileId} />
        ))
      )}
    </div>
  );
}

function OriginalImage({ batchId, fileId }: { batchId: string; fileId: string }) {
  const [url, setUrl] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let revoked: string | null = null;
    blobUrl(`/uploads/batches/${batchId}/files/${fileId}/content`)
      .then((u) => {
        revoked = u;
        setUrl(u);
      })
      .catch(() => setFailed(true));
    return () => {
      if (revoked) URL.revokeObjectURL(revoked);
    };
  }, [batchId, fileId]);
  if (failed) return <EmptyState icon={ImageIcon} title="Original not available" />;
  if (!url) return <Skeleton rows={4} />;
  return (
    <a href={url} target="_blank" rel="noreferrer" title="Open full size">
      <img src={url} alt="Uploaded GETS sheet" className="w-full rounded-lg border border-line" />
    </a>
  );
}

function SheetView({ sheet, view, batchId, fileId }: { sheet: GetsSheet; view: string; batchId: string; fileId: string }) {
  const failed = sheet.checks.filter((c) => !c.ok);
  const totalHours = sheet.lines.reduce((n, l) => n + l.computed_total, 0);
  const leaveDays = sheet.lines.filter((l) => l.is_out_of_office).flatMap((l) => l.cells.filter((c) => c.hours).map((c) => c.day));

  return (
    <div className="space-y-5">
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <Card className="p-5 md:col-span-2">
          <div className="flex items-start justify-between gap-3">
            <div>
              <p className="text-xs uppercase tracking-wider text-ink-3">Employee</p>
              <p className="mt-1 text-lg font-semibold text-ink">{sheet.employee_name || "—"}</p>
              <p className="text-sm text-ink-2">
                ID <span className="font-mono">{sheet.person_id || "—"}</span> · {sheet.supplier} · {sheet.job_family}
              </p>
            </div>
            <StatusBadge status={sheet.status} />
          </div>
        </Card>
        <Card className="p-5">
          <p className="text-xs uppercase tracking-wider text-ink-3">Period</p>
          <p className="mt-1 text-lg font-semibold text-ink">{fmtPeriod(sheet.period)}</p>
          <p className="text-sm text-ink-2">{sheet.days_in_month} days · {sheet.lines.length} projects</p>
        </Card>
        <Card className="p-5">
          <p className="text-xs uppercase tracking-wider text-ink-3">Hours</p>
          <p className="mt-1 text-lg font-semibold tabular-nums text-ink">{fmtHours(totalHours)} h</p>
          <p className="text-sm text-ink-2">
            {leaveDays.length ? `${leaveDays.length} Out Of Office day(s)` : "No Out Of Office"}
          </p>
        </Card>
      </div>

      <div className={view === "split" ? "grid gap-5 2xl:grid-cols-2" : ""}>
        {view !== "grid" && (
          <Card className="p-4">
            <p className="mb-3 flex items-center gap-2 text-sm font-semibold text-ink">
              <ImageIcon className="h-4 w-4 text-ink-3" /> Uploaded screenshot
            </p>
            <OriginalImage batchId={batchId} fileId={fileId} />
          </Card>
        )}
        {view !== "image" && (
          <Card className="overflow-hidden">
            <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-4 py-3">
              <p className="flex items-center gap-2 text-sm font-semibold text-ink">
                {view === "split" ? <Columns2 className="h-4 w-4 text-ink-3" /> : <Table2 className="h-4 w-4 text-ink-3" />}
                Reconstructed timesheet
              </p>
              <div className="flex flex-wrap gap-3 text-xs text-ink-2">
                {LEGEND.map((l) => (
                  <span key={l.key} className="inline-flex items-center gap-1.5">
                    <span className={`h-3 w-3 rounded-sm ${CELL_STYLE[l.key]}`} /> {l.label}
                  </span>
                ))}
              </div>
            </div>
            <TimesheetGrid sheet={sheet} />
          </Card>
        )}
      </div>

      <div className="grid gap-5 lg:grid-cols-2">
        <Card className="p-5">
          <SectionTitle flush>Verification ({sheet.checks.length - failed.length}/{sheet.checks.length} passed)</SectionTitle>
          <ul className="space-y-2" data-testid="checks">
            {sheet.checks.map((c, i) => (
              <li key={i} className="flex items-start gap-2.5 text-sm">
                {c.ok ? (
                  <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-success-700" aria-label="passed" />
                ) : (
                  <XCircle className="mt-0.5 h-4 w-4 shrink-0 text-danger-700" aria-label="failed" />
                )}
                <span className="flex-1 text-ink-2">
                  {c.check}
                  {c.mismatched_days?.length ? (
                    <span className="text-danger-700"> — days {c.mismatched_days.join(", ")}</span>
                  ) : null}
                </span>
                {typeof c.expected === "number" && (
                  <span className="font-mono text-xs text-ink-3">
                    {String(c.actual)} / {String(c.expected)}
                  </span>
                )}
              </li>
            ))}
          </ul>
        </Card>
        <Card className="p-5">
          <SectionTitle flush>Corrections & notes</SectionTitle>
          {sheet.corrections.length === 0 && sheet.warnings.length === 0 && (
            <p className="flex items-center gap-2 text-sm text-ink-2">
              <CheckCircle2 className="h-4 w-4 text-success-700" /> Read cleanly — nothing needed correcting.
            </p>
          )}
          <ul className="space-y-2">
            {sheet.corrections.map((c, i) => (
              <li key={`c${i}`} className="flex items-start gap-2 text-sm text-ink-2">
                <Sparkles className="mt-0.5 h-4 w-4 shrink-0 text-primary-600" /> {c}
              </li>
            ))}
            {sheet.warnings.map((w, i) => (
              <li key={`w${i}`} className="flex items-start gap-2 text-sm text-warning-700">
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" /> {w}
              </li>
            ))}
          </ul>
        </Card>
      </div>
    </div>
  );
}

function TimesheetGrid({ sheet }: { sheet: GetsSheet }) {
  const days = useMemo(() => Array.from({ length: sheet.days_in_month }, (_, i) => i + 1), [sheet.days_in_month]);
  const weekend = (i: number) => sheet.weekdays[i] === "Sa" || sheet.weekdays[i] === "Su";
  const totalsFor = (label: string) => sheet.totals[label];
  const computed = (label: string, day: number) =>
    sheet.lines
      .filter((l) => label === "TOTAL" || l.uom === label)
      .reduce((n, l) => n + (l.cells.find((c) => c.day === day)?.hours ?? 0), 0);

  return (
    <div className="max-h-[70vh] overflow-auto" data-testid="timesheet-grid">
      <table className="min-w-max border-separate border-spacing-0 text-xs">
        <thead className="sticky top-0 z-10 bg-surface-2">
          <tr>
            <th className="sticky left-0 z-20 min-w-[220px] border-b border-line bg-surface-2 px-3 py-2 text-left font-semibold text-ink-2">Project</th>
            <th className="border-b border-line px-2 py-2 font-semibold text-ink-2">UOM</th>
            {days.map((d, i) => (
              <th key={d} className={`w-9 border-b border-line px-0.5 py-1.5 text-center font-semibold ${weekend(i) ? "text-danger-700" : "text-ink-2"}`}>
                <span className="block">{d}</span>
                <span className="block font-normal text-ink-3">{sheet.weekdays[i] ?? ""}</span>
              </th>
            ))}
            <th className="border-b border-line px-3 py-2 text-right font-semibold text-ink-2">Total</th>
          </tr>
        </thead>
        <tbody>
          {sheet.lines.map((line) => (
            <GridRow key={line.row_index} line={line} days={days} weekend={weekend} />
          ))}
          {Object.keys(sheet.totals).map((label) => (
            <tr key={label} className="bg-surface-2/70">
              <td className="sticky left-0 border-t border-line bg-surface-2 px-3 py-1.5 text-right font-semibold text-ink-2" colSpan={1}>
                {label === "TOTAL" ? "Total" : `Totals · ${label}`}
              </td>
              <td className="border-t border-line" />
              {days.map((d, i) => {
                const printed = totalsFor(label)?.[i];
                const ok = printed == null || Math.abs((printed ?? 0) - computed(label, d)) < 1e-6;
                return (
                  <td key={d} className={`border-t border-line text-center tabular-nums ${ok ? "text-ink-2" : "bg-danger-100 font-semibold text-danger-700"}`} title={ok ? undefined : `computed ${computed(label, d)}`}>
                    {printed ?? "?"}
                  </td>
                );
              })}
              <td className="border-t border-line px-3 text-right font-semibold tabular-nums text-ink">
                {sheet.totals_printed_total[label] ?? "—"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function GridRow({ line, days, weekend }: { line: GetsLine; days: number[]; weekend: (i: number) => boolean }) {
  const byDay = new Map(line.cells.map((c) => [c.day, c]));
  const mismatch = line.printed_total != null && Math.abs(line.printed_total - line.computed_total) > 1e-6;
  return (
    <tr className={line.is_out_of_office ? "bg-warning-100/40" : ""}>
      <td className="sticky left-0 z-[1] border-t border-line bg-surface px-3 py-1.5">
        <p className="font-medium text-ink">
          {line.sub_project || "—"}
          {line.is_out_of_office && <Badge tone="warning" className="ml-2">Leave</Badge>}
        </p>
        <p className="font-mono text-[10px] text-ink-3">
          {line.project_id} · {line.sub_project_id}
        </p>
      </td>
      <td className="border-t border-line px-2 text-center font-medium text-ink-2">{line.uom}</td>
      {days.map((d, i) => {
        const c = byDay.get(d);
        const style = c && c.hours != null ? CELL_STYLE[c.status] ?? CELL_STYLE.FILLED : "";
        return (
          <td key={d} className={`border-t border-line p-0.5 text-center ${weekend(i) ? "bg-surface-2/60" : ""}`}>
            {c && c.hours != null ? (
              <span
                className={`flex h-6 items-center justify-center rounded text-[11px] font-semibold tabular-nums ${style} ${c.corrected ? "ring-2 ring-primary-500" : ""}`}
                title={`${c.status.replace("_", " ").toLowerCase()} · read "${c.raw}" (${Math.round(c.confidence * 100)}%)${c.corrected ? " · corrected from totals" : ""}`}
              >
                {fmtHours(c.hours)}
              </span>
            ) : null}
          </td>
        );
      })}
      <td className={`border-t border-line px-3 text-right font-semibold tabular-nums ${mismatch ? "text-danger-700" : "text-ink"}`}>
        {line.printed_total ?? line.computed_total}
      </td>
    </tr>
  );
}

function GenericRows({ rows }: { rows: { row_index: number; data: Record<string, unknown>; needs_review: boolean; review_note: string | null }[] }) {
  const cols = useMemo(() => {
    const keys = new Set<string>();
    rows.forEach((r) => Object.keys(r.data).forEach((k) => k !== "extra" && keys.add(k)));
    return [...keys];
  }, [rows]);
  if (!rows.length) return <Card><EmptyState title="No rows extracted" /></Card>;
  return (
    <Card className="overflow-x-auto">
      <table className="data-table">
        <thead>
          <tr>
            <th>#</th>
            {cols.map((c) => <th key={c}>{c.replace(/_/g, " ")}</th>)}
            <th>Review</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.row_index}>
              <td className="text-ink-3">{r.row_index + 1}</td>
              {cols.map((c) => <td key={c}>{String(r.data[c] ?? "")}</td>)}
              <td>{r.needs_review ? <Badge tone="warning">{r.review_note ?? "review"}</Badge> : <Badge tone="success">OK</Badge>}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Card>
  );
}
