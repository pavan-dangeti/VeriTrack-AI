import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { displayName } from "../lib/display";
import { NAV_SECTIONS, navFor } from "../navigation/nav";

const ROLE_LABEL: Record<string, string> = {
  MASTER_ADMIN: "Master Admin",
  EXECUTIVE: "Executive",
  MANAGER: "Manager",
  HR: "HR",
};

export function DashboardLayout() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  if (!user) return null;
  const items = navFor(user.role);
  const bySection = NAV_SECTIONS.map((s) => ({
    section: s,
    items: items.filter((i) => i.section === s),
  })).filter((g) => g.items.length > 0);

  return (
    <div className="flex min-h-screen bg-canvas">
      <aside className="fixed inset-y-0 left-0 w-64 bg-sidebar" data-testid="sidebar">
        <div className="flex h-16 items-center px-5">
          <span className="text-lg font-bold tracking-tight text-white">
            VeriTrack<span className="text-primary-500"> AI</span>
          </span>
        </div>
        <nav className="mt-2 space-y-1 px-3" aria-label="Main navigation">
          {bySection.map((group, gi) => (
            <div key={group.section} className="space-y-1">
              <p className={`px-3 ${gi === 0 ? "pt-1" : "mt-4 border-t border-sidebar-hover pt-3"} pb-1 text-[10px] font-semibold uppercase tracking-wider text-sidebar-text/70`}>
                {group.section}
              </p>
              {group.items.map((item) => (
                <NavLink
                  key={item.path}
                  to={item.path}
                  className={({ isActive }) =>
                    `block rounded-lg px-3 py-2 text-sm font-medium transition ${
                      isActive
                        ? "bg-sidebar-hover text-white"
                        : "text-sidebar-text hover:bg-sidebar-hover hover:text-white"
                    }`
                  }
                >
                  {item.label}
                </NavLink>
              ))}
            </div>
          ))}
        </nav>
      </aside>

      <div className="ml-64 flex min-h-screen flex-1 flex-col">
        <header className="sticky top-0 z-10 flex h-16 items-center justify-between border-b border-gray-200 bg-surface px-6">
          <div />
          <div className="flex items-center gap-3">
            <NavLink to="/profile" className="text-right hover:opacity-80" data-testid="profile-link">
              <p className="text-sm font-medium text-gray-900">{displayName(user)}</p>
              <p className="text-xs text-gray-500">
                {user.full_name?.trim() ? `${user.email} · ` : ""}{ROLE_LABEL[user.role]}
              </p>
            </NavLink>
            <button
              onClick={async () => {
                await logout();
                navigate("/login");
              }}
              data-testid="logout"
              className="rounded-lg border border-gray-300 px-3 py-1.5 text-sm text-gray-600 hover:bg-canvas"
            >
              Log out
            </button>
          </div>
        </header>
        <main className="flex-1 px-8 py-8">
          <div className="mx-auto max-w-6xl">
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  );
}
