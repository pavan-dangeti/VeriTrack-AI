import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { api, setAccessToken, setRefreshHandler } from "../api/client";

export type Role = "MASTER_ADMIN" | "EXECUTIVE" | "MANAGER" | "HR";

export interface SessionUser {
  id: string;
  email: string;
  full_name?: string | null;
  role: Role;
}

interface AuthState {
  user: SessionUser | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
}

const Ctx = createContext<AuthState>(null!);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<SessionUser | null>(null);
  const [loading, setLoading] = useState(true);

  const doRefresh = useCallback(async (): Promise<boolean> => {
    try {
      const csrf = await api<{ csrf_token: string }>("/auth/csrf", { method: "POST" });
      const r = await fetch("/api/v1/auth/refresh", {
        method: "POST",
        credentials: "include",
        headers: { "X-CSRF-Token": csrf.csrf_token },
      });
      if (!r.ok) return false;
      const data = await r.json();
      setAccessToken(data.access_token);
      return true;
    } catch {
      return false;
    }
  }, []);

  useEffect(() => {
    setRefreshHandler(doRefresh);
    // Restore session from cookie on first load.
    (async () => {
      const ok = await doRefresh();
      if (ok) {
        try {
          setUser(await api<SessionUser>("/auth/me"));
        } catch {
          setAccessToken(null);
        }
      }
      setLoading(false);
    })();
  }, [doRefresh]);

  const login = useCallback(async (email: string, password: string) => {
    const data = await api<{ access_token: string }>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    });
    setAccessToken(data.access_token);
    setUser(await api<SessionUser>("/auth/me"));
  }, []);

  const logout = useCallback(async () => {
    try {
      const csrf = await api<{ csrf_token: string }>("/auth/csrf", { method: "POST" });
      await api("/auth/logout", {
        method: "POST",
        headers: { "X-CSRF-Token": csrf.csrf_token },
      });
    } finally {
      setAccessToken(null);
      setUser(null);
    }
  }, []);

  const value = useMemo(
    () => ({ user, loading, login, logout }),
    [user, loading, login, logout],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAuth() {
  return useContext(Ctx);
}
