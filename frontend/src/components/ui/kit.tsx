import type { ReactNode } from "react";

type Variant = "primary" | "secondary" | "danger" | "ghost";

export function Button({
  children,
  variant = "primary",
  className = "",
  ...props
}: {
  children: ReactNode;
  variant?: Variant;
} & React.ButtonHTMLAttributes<HTMLButtonElement>) {
  const styles: Record<Variant, string> = {
    primary: "bg-primary-600 text-white hover:bg-primary-700",
    secondary:
      "border border-gray-300 bg-surface text-gray-700 hover:bg-canvas",
    danger: "bg-danger-700 text-white hover:opacity-90",
    ghost: "text-primary-600 hover:bg-primary-50",
  };
  return (
    <button
      className={`inline-flex items-center justify-center gap-2 rounded-lg px-3.5 py-2 text-sm font-medium transition disabled:cursor-not-allowed disabled:opacity-50 ${styles[variant]} ${className}`}
      {...props}
    >
      {children}
    </button>
  );
}

export function Card({ children, className = "" }: { children: ReactNode; className?: string }) {
  return (
    <div className={`rounded-xl border border-gray-200/90 bg-surface shadow-card ${className}`}>
      {children}
    </div>
  );
}

export function PageHeader({
  title,
  subtitle,
  actions,
}: {
  title: string;
  subtitle?: string;
  actions?: ReactNode;
}) {
  return (
    <div className="mb-7 flex items-start justify-between gap-4">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-gray-900">{title}</h1>
        {subtitle && <p className="mt-1.5 text-sm text-gray-500">{subtitle}</p>}
      </div>
      {actions && <div className="flex gap-2">{actions}</div>}
    </div>
  );
}

/** Small-caps divider heading between page sections. One look, everywhere. */
export function SectionTitle({ children }: { children: ReactNode }) {
  return (
    <h2 className="mb-3 mt-8 border-b border-gray-200 pb-2 text-xs font-semibold uppercase tracking-wider text-gray-500">
      {children}
    </h2>
  );
}

/** Dashboard-grade metric: the number is the headline. */
export function Stat({ label, value, hint }: { label: string; value: ReactNode; hint?: string }) {
  return (
    <Card className="p-5">
      <p className="text-xs font-medium uppercase tracking-wider text-gray-500">{label}</p>
      <p className="mt-1.5 text-3xl font-semibold tracking-tight text-gray-900">{value}</p>
      {hint && <p className="mt-1 text-xs text-gray-400">{hint}</p>}
    </Card>
  );
}

export function Input({
  label,
  error,
  className = "",
  ...props
}: { label: string; error?: string } & React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <label className="block">
      <span className="mb-1 block text-sm font-medium text-gray-700">{label}</span>
      <input
        className={`w-full rounded-lg border px-3 py-2 text-sm outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-100 ${
          error ? "border-danger-700" : "border-gray-300"
        } ${className}`}
        {...props}
      />
      {error && <span className="mt-1 block text-xs text-danger-700">{error}</span>}
    </label>
  );
}

/** The review-flag visual language. Amber, unmistakable, token-driven (3a). */
export function ReviewBadge({ note }: { note?: string | null }) {
  return (
    <span
      title={note ?? undefined}
      data-testid="review-flag"
      className="inline-flex items-center gap-1 rounded-full border border-warning-700/30 bg-warning-100 px-2 py-0.5 text-xs font-semibold text-warning-700"
    >
      <svg viewBox="0 0 16 16" className="h-3.5 w-3.5 fill-current" aria-hidden>
        <path d="M8 1.5 15 14H1L8 1.5Zm-.75 5v4h1.5v-4h-1.5Zm0 5.25v1.5h1.5v-1.5h-1.5Z" />
      </svg>
      Needs review
    </span>
  );
}

export function StatusBadge({ status }: { status: string }) {
  const map: Record<string, string> = {
    DONE: "bg-success-100 text-success-700",
    COMPLETED: "bg-success-100 text-success-700",
    SENT: "bg-success-100 text-success-700",
    PROCESSING: "bg-primary-50 text-primary-700",
    QUEUED: "bg-gray-100 text-gray-600",
    PENDING_OCR: "bg-warning-100 text-warning-700",
    FAILED: "bg-danger-100 text-danger-700",
    SKIPPED_NO_EMAIL: "bg-warning-100 text-warning-700",
    ERROR: "bg-danger-100 text-danger-700",
    SUCCESS: "bg-success-100 text-success-700",
    DENIED: "bg-danger-100 text-danger-700",
    FAILURE: "bg-danger-100 text-danger-700",
  };
  return (
    <span
      className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${
        map[status] ?? "bg-gray-100 text-gray-600"
      }`}
    >
      {status}
    </span>
  );
}

export function Skeleton({ rows = 5 }: { rows?: number }) {
  return (
    <div className="animate-pulse space-y-3 p-4" data-testid="skeleton">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="h-8 rounded bg-gray-200" />
      ))}
    </div>
  );
}

export function EmptyState({ title, hint }: { title: string; hint?: string }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 py-16 text-center">
      <div className="flex h-11 w-11 items-center justify-center rounded-full bg-gray-100 text-gray-400" aria-hidden>
        <svg viewBox="0 0 20 20" className="h-5 w-5 fill-current">
          <path d="M3 4a1 1 0 0 1 1-1h12a1 1 0 0 1 1 1v2H3V4Zm0 4h14v8a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V8Zm4 3v2h6v-2H7Z" />
        </svg>
      </div>
      <p className="text-sm font-medium text-gray-700">{title}</p>
      {hint && <p className="max-w-sm text-sm text-gray-400">{hint}</p>}
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
  if (!isOpen) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" role="dialog" aria-modal="true" aria-labelledby="pw-title">
      <div className="w-full max-w-md rounded-2xl bg-surface p-6 shadow-xl">
        <div className="flex items-center justify-between mb-4">
          <h2 id="pw-title" className="text-lg font-semibold text-gray-900">Account created</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600" aria-label="Close">
            <svg viewBox="0 0 24 24" className="h-5 w-5 fill-current"><path d="M19 6.41 17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z"/></svg>
          </button>
        </div>
        <p className="text-sm text-gray-600 mb-4">
          <span className="font-medium">{email}</span> created as <span className="font-medium">{role}</span>.
          The initial password is shown <strong>only once</strong> — copy it now.
        </p>
        <div className="relative mb-4">
          <input
            readOnly
            value={password}
            className="w-full rounded-lg border border-gray-300 bg-canvas px-4 py-3 text-sm font-mono text-gray-900 select-all"
            aria-label="Initial password"
          />
          <button
            onClick={() => {
              navigator.clipboard.writeText(password);
              onClose();
            }}
            className="absolute right-2 top-1/2 -translate-y-1/2 text-primary-600 hover:text-primary-700 text-sm font-medium"
          >
            Copy
          </button>
        </div>
        <p className="text-xs text-gray-500">Password copied — dialog will close automatically.</p>
      </div>
    </div>
  );
}
