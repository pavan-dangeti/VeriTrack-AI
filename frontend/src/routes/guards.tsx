import { Navigate, Outlet, useLocation } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { roleCanAccess } from "../navigation/nav";

function SessionLoading() {
  return (
    <div className="flex h-screen items-center justify-center bg-canvas">
      <div className="h-10 w-10 animate-spin rounded-full border-4 border-primary-100 border-t-primary-600" />
    </div>
  );
}

export function RequireAuth() {
  const { user, loading } = useAuth();
  const location = useLocation();
  if (loading) return <SessionLoading />;
  if (!user) {
    return <Navigate to="/login" state={{ from: location.pathname }} replace />;
  }
  return <Outlet />;
}

/** Enforces the nav.ts role map on the route itself (hidden sidebar links are cosmetic). */
export function RequireRole() {
  const { user } = useAuth();
  const location = useLocation();
  if (!user) return <Navigate to="/login" replace />;
  if (!roleCanAccess(user.role, location.pathname)) {
    return <Navigate to="/access-denied" state={{ attempted: location.pathname }} replace />;
  }
  return <Outlet />;
}
