import { createContext, useCallback, useContext, useState, type ReactNode } from "react";

export type ToastKind = "success" | "error" | "info" | "warning";
interface Toast {
  id: number;
  kind: ToastKind;
  message: string;
}

const Ctx = createContext<{ push: (kind: ToastKind, message: string) => void }>(null!);

let nextId = 1;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const push = useCallback((kind: ToastKind, message: string) => {
    const id = nextId++;
    setToasts((t) => [...t, { id, kind, message }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 6000);
  }, []);

  return (
    <Ctx.Provider value={{ push }}>
      {children}
      <div className="fixed right-4 top-4 z-50 flex w-96 flex-col gap-2" aria-live="polite">
        {toasts.map((t) => {
          const dots = {
            success: "bg-success-700",
            error: "bg-danger-700",
            warning: "bg-warning-700",
            info: "bg-primary-600",
          } as const;
          return (
            <div
              key={t.id}
              data-testid={`toast-${t.kind}`}
              className={`flex items-start gap-2.5 rounded-lg border px-4 py-3 text-sm shadow-pop animate-toast-in ${
                t.kind === "success"
                  ? "border-success-700/20 bg-success-100 text-success-700"
                  : t.kind === "error"
                    ? "border-danger-700/20 bg-danger-100 text-danger-700"
                    : t.kind === "warning"
                      ? "border-warning-700/20 bg-warning-100 text-warning-700"
                      : "border-primary-100 bg-primary-50 text-primary-900"
              }`}
            >
              <span className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${dots[t.kind]}`} aria-hidden />
              <span>{t.message}</span>
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
