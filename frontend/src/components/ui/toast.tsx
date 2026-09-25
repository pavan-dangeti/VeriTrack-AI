import { createContext, useCallback, useContext, useState, type ReactNode } from "react";
import { AlertTriangle, CheckCircle2, Info, X, XCircle } from "lucide-react";

type ToastKind = "success" | "error" | "info" | "warning";
interface Toast {
  id: number;
  kind: ToastKind;
  message: string;
}

const Ctx = createContext<{ push: (kind: ToastKind, message: string) => void }>(null!);

let nextId = 1;

const STYLE = {
  success: { icon: CheckCircle2, cls: "text-success-700" },
  error: { icon: XCircle, cls: "text-danger-700" },
  warning: { icon: AlertTriangle, cls: "text-warning-700" },
  info: { icon: Info, cls: "text-primary-600" },
} as const;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const dismiss = useCallback((id: number) => setToasts((t) => t.filter((x) => x.id !== id)), []);

  const push = useCallback(
    (kind: ToastKind, message: string) => {
      const id = nextId++;
      setToasts((t) => [...t.slice(-4), { id, kind, message }]);
      setTimeout(() => dismiss(id), kind === "error" ? 9000 : 5000);
    },
    [dismiss],
  );

  return (
    <Ctx.Provider value={{ push }}>
      {children}
      <div
        className="pointer-events-none fixed inset-x-4 top-4 z-[60] flex flex-col items-end gap-2 sm:left-auto sm:w-96"
        aria-live="polite"
      >
        {toasts.map((t) => {
          const { icon: Icon, cls } = STYLE[t.kind];
          return (
            <div
              key={t.id}
              data-testid={`toast-${t.kind}`}
              role={t.kind === "error" ? "alert" : "status"}
              className="pointer-events-auto flex w-full animate-toast-in items-start gap-3 rounded-xl border border-line bg-surface px-4 py-3 text-sm text-ink shadow-pop"
            >
              <Icon className={`mt-0.5 h-5 w-5 shrink-0 ${cls}`} aria-hidden />
              <span className="flex-1 leading-5">{t.message}</span>
              <button
                onClick={() => dismiss(t.id)}
                className="rounded p-0.5 text-ink-3 hover:text-ink"
                aria-label="Dismiss notification"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
          );
        })}
      </div>
    </Ctx.Provider>
  );
}

export function useToast() {
  return useContext(Ctx).push;
}
