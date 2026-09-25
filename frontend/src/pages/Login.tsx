import { useState } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import { CalendarCheck2, Lock, ScanLine, ShieldCheck, Sparkles } from "lucide-react";
import { useAuth } from "../auth/AuthContext";
import { Button, Input } from "../components/ui/kit";

const FEATURES = [
  { icon: ScanLine, title: "Verified GETS extraction", text: "Every hour is reconciled against the sheet's own totals." },
  { icon: CalendarCheck2, title: "Leave compliance", text: "Out Of Office days matched to the company leave register." },
  { icon: Sparkles, title: "Reports that write themselves", text: "PDF + Excel summaries and automatic notifications." },
];

export function LoginPage() {
  const { login, user } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  // Field-validation errors render under their input; `error` is reserved
  // for the server response (e.g. "Invalid email or password"), which must
  // always be shown — never filtered by what words it happens to contain.
  const [fieldError, setFieldError] = useState<{ email?: string; password?: string }>({});
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const from = (location.state as { from?: string } | null)?.from ?? "/dashboard";

  if (user) return <Navigate to={from} replace />;

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setFieldError({});
    if (!email.includes("@")) return setFieldError({ email: "Enter a valid email address" });
    if (password.length < 8) return setFieldError({ password: "Password must be at least 8 characters" });
    setBusy(true);
    try {
      await login(email.trim(), password);
      navigate(from, { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="grid min-h-screen bg-canvas lg:grid-cols-[1.1fr_1fr]">
      <aside className="relative hidden overflow-hidden bg-sidebar p-12 lg:flex lg:flex-col lg:justify-between">
        <div className="pointer-events-none absolute -left-32 -top-32 h-96 w-96 rounded-full bg-indigo-600/30 blur-3xl" />
        <div className="pointer-events-none absolute -bottom-40 right-0 h-[28rem] w-[28rem] rounded-full bg-violet-600/20 blur-3xl" />
        <div className="relative flex items-center gap-2.5">
          <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-indigo-500 to-violet-600 text-white shadow-lg shadow-indigo-500/30">
            <ShieldCheck className="h-5 w-5" />
          </span>
          <span className="text-lg font-semibold text-white">
            VeriTrack<span className="text-indigo-400"> AI</span>
          </span>
        </div>
        <div className="relative max-w-md">
          <h2 className="text-4xl font-semibold leading-tight tracking-tight text-white">
            Timesheets in. <span className="bg-gradient-to-r from-indigo-300 to-violet-300 bg-clip-text text-transparent">Compliance out.</span>
          </h2>
          <p className="mt-4 text-base text-slate-400">
            Upload GETS screenshots and get accurate, verified hours and leave checks — for every employee, every month.
          </p>
          <ul className="mt-10 space-y-5">
            {FEATURES.map((f) => (
              <li key={f.title} className="flex gap-3.5">
                <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-white/5 text-indigo-300 ring-1 ring-white/10">
                  <f.icon className="h-4.5 w-4.5" />
                </span>
                <span>
                  <span className="block text-sm font-semibold text-white">{f.title}</span>
                  <span className="block text-sm text-slate-400">{f.text}</span>
                </span>
              </li>
            ))}
          </ul>
        </div>
        <p className="relative text-xs text-slate-500">© {new Date().getFullYear()} VeriTrack AI · Enterprise compliance platform</p>
      </aside>

      <main className="flex items-center justify-center p-6">
        <div className="w-full max-w-sm animate-fade-up">
          <div className="mb-8 flex items-center gap-2.5 lg:hidden">
            <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-gradient-to-br from-indigo-500 to-violet-600 text-white">
              <ShieldCheck className="h-5 w-5" />
            </span>
            <span className="text-lg font-semibold text-ink">
              VeriTrack<span className="text-primary-600"> AI</span>
            </span>
          </div>
          <h1 className="text-2xl font-semibold tracking-tight text-ink">Welcome back</h1>
          <p className="mt-1.5 mb-8 text-sm text-ink-2">Sign in to your compliance workspace.</p>
          <form onSubmit={submit} className="space-y-4" noValidate>
            <Input
              label="Email"
              type="email"
              autoComplete="username"
              placeholder="you@company.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              error={fieldError.email}
            />
            <Input
              label="Password"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              error={fieldError.password}
            />
            {error && (
              <p className="rounded-lg bg-danger-100 px-3 py-2 text-sm text-danger-700" data-testid="login-error" role="alert">
                {error}
              </p>
            )}
            <Button type="submit" size="lg" loading={busy} className="w-full" icon={Lock}>
              {busy ? "Signing in…" : "Sign in"}
            </Button>
          </form>
          <p className="mt-6 text-center text-xs text-ink-3">
            Accounts are created by your administrator. Sessions are secured with rotating tokens.
          </p>
        </div>
      </main>
    </div>
  );
}

export function AccessDeniedPage() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  // RequireRole redirects here with the blocked URL in router state.
  const attempted = (location.state as { attempted?: string } | null)?.attempted ?? location.pathname;
  return (
    <div className="flex min-h-screen items-center justify-center bg-canvas p-6">
      <div className="max-w-md animate-fade-up rounded-2xl border border-line bg-surface p-8 text-center shadow-card">
        <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-2xl bg-danger-100 text-danger-700">
          <Lock className="h-6 w-6" />
        </div>
        <h1 className="text-lg font-semibold text-ink">Access denied</h1>
        <p className="mt-2 text-sm text-ink-2" data-testid="denied-path">
          Your role ({user?.role}) does not have permission to view{" "}
          <code className="rounded bg-surface-2 px-1">{attempted}</code>.
        </p>
        <Button variant="secondary" className="mt-6" onClick={() => navigate("/dashboard")}>
          Back to dashboard
        </Button>
      </div>
    </div>
  );
}
