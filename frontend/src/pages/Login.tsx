import { useState } from "react";
import { Navigate, useNavigate, useLocation } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { Button, Input } from "../components/ui/kit";

export function LoginPage() {
  const { login, user } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (user) return <Navigate to="/dashboard" replace />;

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    if (!email.includes("@")) return setError("Enter a valid email address");
    if (password.length < 8) return setError("Password must be at least 8 characters");
    setBusy(true);
    try {
      await login(email, password);
      navigate("/dashboard");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-canvas">
      <div className="w-full max-w-sm rounded-2xl border border-gray-200 bg-surface p-8 shadow-sm">
        <h1 className="text-xl font-bold text-gray-900">
          VeriTrack<span className="text-primary-600"> AI</span>
        </h1>
        <p className="mt-1 mb-6 text-sm text-gray-500">
          Employee leave compliance & document intelligence
        </p>
        <form onSubmit={submit} className="space-y-4" noValidate>
          <Input
            label="Email"
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            error={error && !email.includes("@") ? "Enter a valid email address" : undefined}
          />
          <Input
            label="Password"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            error={error?.includes("Password") ? error : undefined}
          />
          {error && !error.includes("Password") && !error.includes("email") && (
            <p className="text-sm text-danger-700" data-testid="login-error">
              {error}
            </p>
          )}
          <Button type="submit" disabled={busy} className="w-full">
            {busy ? "Signing in…" : "Sign in"}
          </Button>
        </form>
      </div>
    </div>
  );
}

export function AccessDeniedPage() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  return (
    <div className="flex min-h-screen items-center justify-center bg-canvas">
      <div className="max-w-md rounded-2xl border border-danger-700/20 bg-surface p-8 text-center shadow-sm">
        <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-danger-100">
          <svg viewBox="0 0 20 20" className="h-6 w-6 fill-danger-700">
            <path d="M10 2a4 4 0 0 0-4 4v2H5a2 2 0 0 0-2 2v6a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-6a2 2 0 0 0-2-2h-1V6a4 4 0 0 0-4-4Zm2 6H8V6a2 2 0 1 1 4 0v2Z" />
          </svg>
        </div>
        <h1 className="text-lg font-semibold text-gray-900">Access denied</h1>
        <p className="mt-2 text-sm text-gray-500" data-testid="denied-path">
          Your role ({user?.role}) does not have permission to view{" "}
          <code className="rounded bg-canvas px-1">{location.pathname}</code>.
        </p>
        <Button variant="secondary" className="mt-6" onClick={() => navigate("/dashboard")}>
          Back to dashboard
        </Button>
      </div>
    </div>
  );
}
