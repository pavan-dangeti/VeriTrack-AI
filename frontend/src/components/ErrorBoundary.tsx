import { Component, type ErrorInfo, type ReactNode } from "react";

interface Props {
  children: ReactNode;
}

interface State {
  error: Error | null;
}

/** A broken subtree must never white-screen the whole app. */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // eslint-disable-next-line no-console
    console.error("ui_crash", error, info.componentStack);
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div className="flex min-h-screen items-center justify-center bg-canvas p-6" data-testid="error-boundary">
        <div className="w-full max-w-md rounded-xl border border-gray-200/90 bg-surface p-8 text-center shadow-card">
          <div className="mx-auto mb-4 flex h-11 w-11 items-center justify-center rounded-full bg-danger-100 text-danger-700" aria-hidden>
            <svg viewBox="0 0 20 20" className="h-5 w-5 fill-current">
              <path d="M10 2a1 1 0 0 1 .9.55l7 14A1 1 0 0 1 17 18H3a1 1 0 0 1-.9-1.45l7-14A1 1 0 0 1 10 2Zm0 6a.75.75 0 0 0-.75.75v3.5a.75.75 0 0 0 1.5 0v-3.5A.75.75 0 0 0 10 8Zm0 6.25a.875.875 0 1 0 0 1.75.875.875 0 0 0 0-1.75Z" />
            </svg>
          </div>
          <h1 className="text-lg font-semibold text-gray-900">Something went wrong</h1>
          <p className="mt-2 text-sm text-gray-500">
            This part of the app hit an unexpected error. Your data is safe —
            reloading usually fixes it. If it keeps happening, report the error text below.
          </p>
          <p className="mt-3 select-all rounded-lg bg-canvas px-3 py-2 font-mono text-xs text-gray-500">
            {this.state.error.message}
          </p>
          <button
            onClick={() => window.location.assign("/dashboard")}
            className="mt-5 inline-flex items-center justify-center rounded-lg bg-primary-600 px-4 py-2 text-sm font-medium text-white hover:bg-primary-700"
            data-testid="error-reload"
          >
            Reload app
          </button>
        </div>
      </div>
    );
  }
}
