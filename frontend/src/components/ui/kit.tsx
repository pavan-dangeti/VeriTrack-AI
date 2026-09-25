import { useCallback, useEffect, useId, useRef, useState, type ReactNode } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  Copy,
  Inbox,
  Loader2,
  UploadCloud,
  X,
  type LucideIcon,
} from "lucide-react";

type Variant = "primary" | "secondary" | "danger" | "ghost" | "subtle";
type Size = "sm" | "md" | "lg";

function Spinner({ className = "h-4 w-4" }: { className?: string }) {
  return <Loader2 className={`animate-spin ${className}`} aria-hidden />;
}

export function Button({
  children,
  variant = "primary",
  size = "md",
  loading = false,
  icon: Icon,
  className = "",
  disabled,
  ...props
}: {
  children?: ReactNode;
  variant?: Variant;
  size?: Size;
  loading?: boolean;
  icon?: LucideIcon;
} & React.ButtonHTMLAttributes<HTMLButtonElement>) {
  const styles: Record<Variant, string> = {
    primary:
      "bg-primary-600 text-white shadow-sm hover:bg-primary-700 dark:hover:bg-primary-500 active:translate-y-px",
    secondary:
      "border border-line bg-surface text-ink shadow-sm hover:bg-surface-2 active:translate-y-px",
    danger: "bg-danger-500 text-white shadow-sm hover:brightness-95 active:translate-y-px",
    ghost: "text-primary-600 hover:bg-primary-50 dark:text-primary-700",
    subtle: "bg-surface-2 text-ink-2 hover:text-ink hover:bg-primary-50",
  };
  const sizes: Record<Size, string> = {
    sm: "h-8 px-2.5 text-xs",
    md: "h-9 px-3.5 text-sm",
    lg: "h-11 px-5 text-sm",
  };
  return (
    <button
      className={`inline-flex select-none items-center justify-center gap-2 whitespace-nowrap rounded-lg font-medium transition duration-150 disabled:cursor-not-allowed disabled:opacity-50 ${styles[variant]} ${sizes[size]} ${className}`}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      {...props}
    >
      {loading ? <Spinner /> : Icon ? <Icon className="h-4 w-4" aria-hidden /> : null}
      {children}
    </button>
  );
}

export function Card({
  children,
  className = "",
  ...rest
}: { children: ReactNode; className?: string } & React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div className={`rounded-2xl border border-line bg-surface shadow-card ${className}`} {...rest}>
      {children}
    </div>
  );
}

export function PageHeader({
  title,
  subtitle,
  actions,
  eyebrow,
}: {
  title: string;
  subtitle?: string;
  actions?: ReactNode;
  eyebrow?: ReactNode;
}) {
  return (
    <div className="mb-7 flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
      {/* long unbroken strings (email-as-name) must wrap, not widen the page */}
      <div className="min-w-0 [overflow-wrap:anywhere]">
        {eyebrow && <div className="mb-1.5 text-xs font-medium text-primary-600">{eyebrow}</div>}
        <h1 className="text-2xl font-semibold tracking-tight text-ink sm:text-[28px]">{title}</h1>
        {subtitle && <p className="mt-1.5 max-w-2xl text-sm text-ink-2">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </div>
  );
}

export function SectionTitle({ children, action, flush = false }: { children: ReactNode; action?: ReactNode; flush?: boolean }) {
  return (
    <div className={`mb-3 ${flush ? "" : "mt-8"} flex items-center justify-between border-b border-line pb-2`}>
      <h2 className="text-[11px] font-semibold uppercase tracking-wider text-ink-3">{children}</h2>
      {action}
    </div>
  );
}

export function Stat({
  label,
  value,
  hint,
  icon: Icon,
  tone = "primary",
}: {
  label: string;
  value: ReactNode;
  hint?: string;
  icon?: LucideIcon;
  tone?: "primary" | "success" | "warning" | "danger";
}) {
  const tones = {
    primary: "bg-primary-50 text-primary-600",
    success: "bg-success-100 text-success-700",
    warning: "bg-warning-100 text-warning-700",
    danger: "bg-danger-100 text-danger-700",
  };
  return (
    <Card className="p-5 transition hover:-translate-y-0.5 hover:shadow-pop">
      <div className="flex items-start justify-between gap-3">
        <p className="text-xs font-medium uppercase tracking-wider text-ink-3">{label}</p>
        {Icon && (
          <span className={`flex h-8 w-8 items-center justify-center rounded-lg ${tones[tone]}`}>
            <Icon className="h-4 w-4" aria-hidden />
          </span>
        )}
      </div>
      <p className="mt-2 text-3xl font-semibold tabular-nums tracking-tight text-ink">{value}</p>
      {hint && <p className="mt-1 text-xs text-ink-3">{hint}</p>}
    </Card>
  );
}

export function Input({
  label,
  error,
  hint,
  className = "",
  ...props
}: { label: string; error?: string; hint?: string } & React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-sm font-medium text-ink">{label}</span>
      <input
        className={`h-10 w-full rounded-lg border bg-surface px-3 text-sm text-ink outline-none transition placeholder:text-ink-3 focus:border-primary-500 focus:shadow-glow ${
          error ? "border-danger-500" : "border-line"
        } ${className}`}
        aria-invalid={error ? true : undefined}
        {...props}
      />
      {error ? (
        <span className="mt-1 block text-xs text-danger-700">{error}</span>
      ) : hint ? (
        <span className="mt-1 block text-xs text-ink-3">{hint}</span>
      ) : null}
    </label>
  );
}

type Tone = "neutral" | "primary" | "success" | "warning" | "danger";
const TONES: Record<Tone, string> = {
  neutral: "bg-surface-2 text-ink-2 ring-line",
  primary: "bg-primary-50 text-primary-700 ring-primary-200",
  success: "bg-success-100 text-success-700 ring-success-500/25",
  warning: "bg-warning-100 text-warning-700 ring-warning-500/30",
  danger: "bg-danger-100 text-danger-700 ring-danger-500/25",
};

export function Badge({
  children,
  tone = "neutral",
  dot = false,
  className = "",
  ...rest
}: { children: ReactNode; tone?: Tone; dot?: boolean; className?: string } & React.HTMLAttributes<HTMLSpanElement>) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${TONES[tone]} ${className}`}
      {...rest}
    >
      {dot && <span className="h-1.5 w-1.5 rounded-full bg-current" aria-hidden />}
      {children}
    </span>
  );
}

export function ReviewBadge({ note }: { note?: string | null }) {
  return (
    <span
      title={note ?? undefined}
      data-testid="review-flag"
      className="inline-flex items-center gap-1 rounded-full bg-warning-100 px-2 py-0.5 text-xs font-semibold text-warning-700 ring-1 ring-inset ring-warning-500/30"
    >
      <AlertTriangle className="h-3.5 w-3.5" aria-hidden />
      Needs review
    </span>
  );
}

const STATUS: Record<string, { label: string; tone: Tone }> = {
  DONE: { label: "Done", tone: "success" },
  COMPLETED: { label: "Completed", tone: "success" },
  SENT: { label: "Sent", tone: "success" },
  SUCCESS: { label: "Success", tone: "success" },
  VERIFIED: { label: "Verified", tone: "success" },
  CORRECTED: { label: "Auto-corrected", tone: "primary" },
  NEEDS_REVIEW: { label: "Needs review", tone: "warning" },
  PROCESSING: { label: "Processing", tone: "primary" },
  RUNNING: { label: "Running", tone: "primary" },
  QUEUED: { label: "Queued", tone: "neutral" },
  PENDING: { label: "Pending", tone: "neutral" },
  PENDING_OCR: { label: "Awaiting OCR", tone: "warning" },
  SKIPPED_NO_EMAIL: { label: "No email on file", tone: "warning" },
  FAILED: { label: "Failed", tone: "danger" },
  ERROR: { label: "Error", tone: "danger" },
  DENIED: { label: "Denied", tone: "danger" },
  FAILURE: { label: "Failure", tone: "danger" },
  ACTIVE: { label: "Active", tone: "success" },
  DISABLED: { label: "Disabled", tone: "neutral" },
};

export function StatusBadge({ status }: { status: string }) {
  const s = STATUS[status] ?? { label: status, tone: "neutral" as Tone };
  const live = status === "PROCESSING" || status === "RUNNING";
  return (
    <Badge tone={s.tone} dot data-status={status} className={live ? "[&>span:first-child]:animate-pulse" : ""}>
      {s.label}
    </Badge>
  );
}

export function ProgressBar({ value, max, tone = "primary" }: { value: number; max: number; tone?: Tone }) {
  const pct = max > 0 ? Math.min(100, Math.round((value / max) * 100)) : 0;
  const bar = { primary: "bg-primary-500", success: "bg-success-500", warning: "bg-warning-500", danger: "bg-danger-500", neutral: "bg-ink-3" }[tone];
  return (
    <div className="h-1.5 w-full overflow-hidden rounded-full bg-surface-2" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
      <div className={`h-full rounded-full transition-all duration-500 ${bar}`} style={{ width: `${pct}%` }} />
    </div>
  );
}

export function Skeleton({ rows = 5 }: { rows?: number }) {
  return (
    <div className="space-y-3 p-4" data-testid="skeleton" aria-busy="true" aria-label="Loading">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="skeleton-bar h-9" style={{ opacity: 1 - i * 0.12 }} />
      ))}
    </div>
  );
}

export function EmptyState({
  title,
  hint,
  icon: Icon = Inbox,
  action,
}: {
  title: string;
  hint?: string;
  icon?: LucideIcon;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 px-6 py-16 text-center">
      <div className="mb-1 flex h-12 w-12 items-center justify-center rounded-2xl bg-primary-50 text-primary-600" aria-hidden>
        <Icon className="h-6 w-6" />
      </div>
      <p className="text-sm font-semibold text-ink">{title}</p>
      {hint && <p className="max-w-sm text-sm text-ink-3">{hint}</p>}
      {action && <div className="mt-3">{action}</div>}
    </div>
  );
}

/** Accessible modal: focus moves in, Esc closes, backdrop click closes. */
export function Modal({
  open,
  onClose,
  title,
  children,
  footer,
  size = "md",
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
  footer?: ReactNode;
  size?: "md" | "lg";
}) {
  const titleId = useId();
  const panel = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    document.addEventListener("keydown", onKey);
    panel.current?.focus();
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div
      className="fixed inset-0 z-50 flex items-end justify-center bg-black/50 p-4 backdrop-blur-sm sm:items-center"
      onMouseDown={(e) => e.target === e.currentTarget && onClose()}
    >
      <div
        ref={panel}
        tabIndex={-1}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className={`w-full ${size === "lg" ? "max-w-3xl" : "max-w-md"} animate-fade-up rounded-2xl border border-line bg-surface shadow-pop outline-none`}
      >
        <div className="flex items-center justify-between border-b border-line px-6 py-4">
          <h2 id={titleId} className="text-base font-semibold text-ink">{title}</h2>
          <button onClick={onClose} className="rounded-lg p-1 text-ink-3 hover:bg-surface-2 hover:text-ink" aria-label="Close">
            <X className="h-5 w-5" />
          </button>
        </div>
        <div className="px-6 py-5">{children}</div>
        {footer && <div className="flex justify-end gap-2 border-t border-line px-6 py-4">{footer}</div>}
      </div>
    </div>
  );
}

export function Tabs<T extends string>({
  tabs,
  value,
  onChange,
}: {
  tabs: { id: T; label: string; count?: number; testId?: string }[];
  value: T;
  onChange: (id: T) => void;
}) {
  return (
    <div className="mb-4 inline-flex rounded-xl border border-line bg-surface-2 p-1" role="tablist">
      {tabs.map((t) => (
        <button
          key={t.id}
          role="tab"
          aria-selected={value === t.id}
          data-testid={t.testId}
          onClick={() => onChange(t.id)}
          className={`rounded-lg px-3 py-1.5 text-sm font-medium transition ${
            value === t.id ? "bg-surface text-ink shadow-card" : "text-ink-2 hover:text-ink"
          }`}
        >
          {t.label}
          {t.count != null && (
            <span className="ml-1.5 rounded-full bg-primary-50 px-1.5 text-xs text-primary-700">{t.count}</span>
          )}
        </button>
      ))}
    </div>
  );
}

export function Dropzone({
  accept,
  onFiles,
  busy = false,
  title = "Drop files here or click to browse",
  hint,
  testId,
}: {
  accept: string[];
  onFiles: (files: File[]) => void;
  busy?: boolean;
  title?: string;
  hint?: string;
  testId?: string;
}) {
  const input = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);
  const take = useCallback(
    (list: FileList | null) => {
      const files = Array.from(list ?? []);
      if (files.length) onFiles(files);
    },
    [onFiles],
  );
  return (
    <div
      onDragOver={(e) => {
        e.preventDefault();
        setOver(true);
      }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => {
        e.preventDefault();
        setOver(false);
        if (!busy) take(e.dataTransfer.files);
      }}
      onClick={() => !busy && input.current?.click()}
      onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && !busy && input.current?.click()}
      role="button"
      tabIndex={0}
      aria-disabled={busy}
      className={`group flex cursor-pointer flex-col items-center justify-center gap-2 rounded-2xl border-2 border-dashed px-6 py-9 text-center transition ${
        over ? "border-primary-500 bg-primary-50" : "border-line bg-surface hover:border-primary-200 hover:bg-surface-2"
      } ${busy ? "cursor-wait opacity-70" : ""}`}
    >
      <input
        ref={input}
        type="file"
        multiple
        hidden
        accept={accept.map((e) => "." + e).join(",")}
        data-testid={testId}
        onChange={(e) => {
          take(e.target.files);
          e.target.value = "";
        }}
      />
      <span className="flex h-12 w-12 items-center justify-center rounded-2xl bg-primary-50 text-primary-600 transition group-hover:scale-105">
        {busy ? <Spinner className="h-6 w-6" /> : <UploadCloud className="h-6 w-6" aria-hidden />}
      </span>
      <p className="text-sm font-semibold text-ink">{busy ? "Uploading…" : title}</p>
      {hint && <p className="max-w-md text-xs text-ink-3">{hint}</p>}
    </div>
  );
}

export function PasswordModal({
  isOpen,
  onClose,
  password,
  email,
  role,
}: {
  isOpen: boolean;
  onClose: () => void;
  password: string;
  email: string;
  role: string;
}) {
  const [copied, setCopied] = useState(false);
  return (
    <Modal open={isOpen} onClose={onClose} title="Account created">
      <p className="mb-4 text-sm text-ink-2">
        <span className="font-medium text-ink">{email}</span> created as{" "}
        <span className="font-medium text-ink">{role}</span>. The initial password is shown{" "}
        <strong>only once</strong> — copy it now.
      </p>
      <div className="relative mb-3">
        <input
          readOnly
          value={password}
          className="h-11 w-full select-all rounded-lg border border-line bg-surface-2 px-4 pr-20 font-mono text-sm text-ink"
          aria-label="Initial password"
        />
        <button
          onClick={() => {
            navigator.clipboard?.writeText(password);
            setCopied(true);
            setTimeout(onClose, 600);
          }}
          className="absolute right-2 top-1/2 inline-flex -translate-y-1/2 items-center gap-1 rounded-md px-2 py-1 text-sm font-medium text-primary-600 hover:bg-primary-50"
        >
          {copied ? <CheckCircle2 className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
          Copy
        </button>
      </div>
      <p className="text-xs text-ink-3">The dialog closes after copying.</p>
    </Modal>
  );
}

export function Kbd({ children }: { children: ReactNode }) {
  return (
    <kbd className="rounded border border-line bg-surface-2 px-1.5 py-0.5 font-mono text-[10px] text-ink-3">
      {children}
    </kbd>
  );
}
