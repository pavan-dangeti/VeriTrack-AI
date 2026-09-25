import { Suspense, useEffect, useMemo, useRef, useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import {
  ChevronsLeft,
  ChevronsRight,
  LogOut,
  Menu,
  Moon,
  Search,
  ShieldCheck,
  Sun,
  X,
} from "lucide-react";
import { useAuth } from "../auth/AuthContext";
import { displayName } from "../lib/display";
import { useTheme } from "../lib/theme";
import { NAV_SECTIONS, navFor, type NavItem } from "../navigation/nav";
import { useBatchCompletionWatcher } from "../api/hooks";
import { useToast } from "../components/ui/toast";
import { Kbd, Skeleton } from "../components/ui/kit";

const ROLE_LABEL: Record<string, string> = {
  MASTER_ADMIN: "Master Admin",
  EXECUTIVE: "Executive",
  MANAGER: "Manager",
  HR: "HR",
};

function initials(name: string) {
  return name
    .split(/[\s@.]+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((p) => p[0]?.toUpperCase())
    .join("");
}

function readCollapsed(): boolean {
  try {
    return localStorage.getItem("vt-sidebar") === "collapsed";
  } catch {
    return false;
  }
}

/** Fires completion toasts for a manager's batches on whatever page they are. */
function BatchWatcher() {
  const toast = useToast();
  const qc = useQueryClient();
  useBatchCompletionWatcher(({ status, failed, kind }) => {
    qc.invalidateQueries({ queryKey: ["batches"] });
    qc.invalidateQueries({ queryKey: ["employees"] });
    qc.invalidateQueries({ queryKey: ["leaves"] });
    const what = kind === "EMPLOYEE_REPO" ? "Repository upload" : kind === "COMPANY_LEAVE" ? "Leave register upload" : "GETS batch";
    if (status === "COMPLETED") toast("success", `${what} processed`);
    else if (status === "FAILED") toast("error", `${what} failed (${failed} file${failed === 1 ? "" : "s"})`);
  });
  return null;
}

export function DashboardLayout() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const { theme, toggle } = useTheme();
  const [collapsed, setCollapsed] = useState(readCollapsed);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [paletteOpen, setPaletteOpen] = useState(false);

  useEffect(() => {
    try {
      localStorage.setItem("vt-sidebar", collapsed ? "collapsed" : "open");
    } catch {
      /* non-fatal */
    }
  }, [collapsed]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setPaletteOpen((o) => !o);
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  if (!user) return null;
  const items = navFor(user.role);
  const bySection = NAV_SECTIONS.map((s) => ({
    section: s,
    items: items.filter((i) => i.section === s),
  })).filter((g) => g.items.length > 0);
  const name = displayName(user);

  const sidebar = (compact: boolean) => (
    <div className="flex h-full flex-col">
      <div className={`flex h-16 items-center ${compact ? "justify-center" : "gap-2.5 px-5"}`}>
        <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-gradient-to-br from-indigo-500 to-violet-600 text-white shadow-lg shadow-indigo-500/30">
          <ShieldCheck className="h-4.5 w-4.5" aria-hidden />
        </span>
        {!compact && (
          <span className="text-[15px] font-semibold tracking-tight text-white">
            VeriTrack<span className="text-indigo-400"> AI</span>
          </span>
        )}
      </div>
      <nav className="flex-1 space-y-1 overflow-y-auto px-3 pb-4" aria-label="Main navigation">
        {bySection.map((group, gi) => (
          <div key={group.section} className="space-y-0.5">
            {!compact ? (
              <p className={`px-3 ${gi === 0 ? "pt-1" : "mt-4 pt-3"} pb-1.5 text-[10px] font-semibold uppercase tracking-wider text-sidebar-text/60`}>
                {group.section}
              </p>
            ) : (
              gi > 0 && <div className="mx-3 my-3 border-t border-sidebar-hover" />
            )}
            {group.items.map((item) => (
              <SideLink key={item.path} item={item} compact={compact} />
            ))}
          </div>
        ))}
      </nav>
    </div>
  );

  return (
    <div className="min-h-screen bg-canvas">
      {user.role === "MANAGER" && <BatchWatcher />}

      <aside
        className={`fixed inset-y-0 left-0 z-30 hidden bg-sidebar transition-[width] duration-200 lg:block ${collapsed ? "w-[72px]" : "w-64"}`}
        data-testid="sidebar"
      >
        {sidebar(collapsed)}
        <button
          onClick={() => setCollapsed((c) => !c)}
          className="absolute -right-3 top-20 flex h-6 w-6 items-center justify-center rounded-full border border-line bg-surface text-ink-3 shadow-card hover:text-ink"
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
        >
          {collapsed ? <ChevronsRight className="h-3.5 w-3.5" /> : <ChevronsLeft className="h-3.5 w-3.5" />}
        </button>
      </aside>

      {mobileOpen && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <div className="absolute inset-0 bg-black/50 backdrop-blur-sm" onClick={() => setMobileOpen(false)} />
          <aside
            className="absolute inset-y-0 left-0 w-72 animate-fade-up bg-sidebar shadow-pop"
            onClick={(e) => (e.target as HTMLElement).closest("a") && setMobileOpen(false)}
          >
            <button
              onClick={() => setMobileOpen(false)}
              className="absolute right-3 top-4 rounded-lg p-1.5 text-sidebar-text hover:bg-sidebar-hover"
              aria-label="Close menu"
            >
              <X className="h-5 w-5" />
            </button>
            {sidebar(false)}
          </aside>
        </div>
      )}

      <div className={`flex min-h-screen flex-col transition-[padding] duration-200 ${collapsed ? "lg:pl-[72px]" : "lg:pl-64"}`}>
        <header className="sticky top-0 z-20 flex h-16 items-center gap-3 border-b border-line bg-surface/80 px-4 backdrop-blur-xl sm:px-6">
          <button
            onClick={() => setMobileOpen(true)}
            className="rounded-lg p-2 text-ink-2 hover:bg-surface-2 lg:hidden"
            aria-label="Open menu"
          >
            <Menu className="h-5 w-5" />
          </button>
          <button
            onClick={() => setPaletteOpen(true)}
            className="flex h-9 w-full max-w-sm items-center gap-2 rounded-lg border border-line bg-surface-2 px-3 text-sm text-ink-3 transition hover:border-primary-200"
            data-testid="open-palette"
          >
            <Search className="h-4 w-4" aria-hidden />
            <span className="flex-1 text-left">Jump to…</span>
            <span className="hidden sm:inline"><Kbd>Ctrl</Kbd> <Kbd>K</Kbd></span>
          </button>
          <div className="ml-auto flex items-center gap-1.5">
            <button
              onClick={toggle}
              className="rounded-lg p-2 text-ink-2 transition hover:bg-surface-2 hover:text-ink"
              aria-label={theme === "dark" ? "Switch to light theme" : "Switch to dark theme"}
              data-testid="theme-toggle"
            >
              {theme === "dark" ? <Sun className="h-5 w-5" /> : <Moon className="h-5 w-5" />}
            </button>
            <NavLink
              to="/profile"
              className="flex items-center gap-2.5 rounded-lg px-2 py-1.5 hover:bg-surface-2"
              data-testid="profile-link"
            >
              <span className="flex h-8 w-8 items-center justify-center rounded-full bg-gradient-to-br from-indigo-500 to-violet-600 text-xs font-semibold text-white">
                {initials(name)}
              </span>
              <span className="hidden text-left md:block">
                <span className="block text-sm font-medium leading-4 text-ink">{name}</span>
                <span className="block text-xs text-ink-3">
                  {user.full_name?.trim() ? `${user.email} · ` : ""}{ROLE_LABEL[user.role]}
                </span>
              </span>
            </NavLink>
            <button
              onClick={async () => {
                await logout();
                navigate("/login");
              }}
              data-testid="logout"
              className="rounded-lg p-2 text-ink-2 transition hover:bg-danger-100 hover:text-danger-700"
              aria-label="Log out"
              title="Log out"
            >
              <LogOut className="h-5 w-5" />
            </button>
          </div>
        </header>

        <main className="flex-1 px-4 py-6 sm:px-8 sm:py-8">
          <div className="mx-auto max-w-7xl animate-fade-up" key={location.pathname}>
            <Suspense fallback={<Skeleton rows={6} />}>
              <Outlet />
            </Suspense>
          </div>
        </main>
      </div>

      {paletteOpen && <CommandPalette items={items} onClose={() => setPaletteOpen(false)} />}
    </div>
  );
}

function SideLink({ item, compact }: { item: NavItem; compact: boolean }) {
  const Icon = item.icon;
  return (
    <NavLink
      to={item.path}
      title={compact ? item.label : undefined}
      className={({ isActive }) =>
        `group relative flex items-center gap-3 rounded-lg ${compact ? "justify-center px-0 py-2.5" : "px-3 py-2"} text-sm font-medium transition ${
          isActive
            ? "bg-sidebar-hover text-white before:absolute before:left-0 before:top-1.5 before:bottom-1.5 before:w-0.5 before:rounded-full before:bg-indigo-400"
            : "text-sidebar-text hover:bg-sidebar-hover hover:text-white"
        }`
      }
    >
      {Icon && <Icon className="h-[18px] w-[18px] shrink-0" aria-hidden />}
      {!compact && <span className="truncate">{item.label}</span>}
    </NavLink>
  );
}

/** Ctrl/⌘+K navigation: type to filter, arrows to move, Enter to go. */
function CommandPalette({ items, onClose }: { items: NavItem[]; onClose: () => void }) {
  const [q, setQ] = useState("");
  const [idx, setIdx] = useState(0);
  const navigate = useNavigate();
  const input = useRef<HTMLInputElement>(null);
  const results = useMemo(() => {
    const t = q.trim().toLowerCase();
    return items.filter(
      (i) => !t || i.label.toLowerCase().includes(t) || (i.hint ?? "").toLowerCase().includes(t),
    );
  }, [items, q]);
  useEffect(() => input.current?.focus(), []);

  const go = (item?: NavItem) => {
    if (!item) return;
    navigate(item.path);
    onClose();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center bg-black/50 p-4 pt-[12vh] backdrop-blur-sm" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="w-full max-w-lg animate-fade-up overflow-hidden rounded-2xl border border-line bg-surface shadow-pop" role="dialog" aria-label="Command palette">
        <div className="flex items-center gap-3 border-b border-line px-4">
          <Search className="h-4 w-4 text-ink-3" aria-hidden />
          <input
            ref={input}
            value={q}
            onChange={(e) => {
              setQ(e.target.value);
              setIdx(0);
            }}
            onKeyDown={(e) => {
              if (e.key === "Escape") onClose();
              if (e.key === "ArrowDown") setIdx((i) => Math.min(i + 1, results.length - 1));
              if (e.key === "ArrowUp") setIdx((i) => Math.max(i - 1, 0));
              if (e.key === "Enter") go(results[idx]);
            }}
            placeholder="Search pages…"
            className="h-12 flex-1 bg-transparent text-sm text-ink outline-none placeholder:text-ink-3"
            aria-label="Search pages"
          />
          <Kbd>Esc</Kbd>
        </div>
        <ul className="max-h-80 overflow-y-auto p-2" role="listbox">
          {results.length === 0 && <li className="px-3 py-6 text-center text-sm text-ink-3">No matches</li>}
          {results.map((item, i) => {
            const Icon = item.icon;
            return (
              <li key={item.path} role="option" aria-selected={i === idx}>
                <button
                  onMouseEnter={() => setIdx(i)}
                  onClick={() => go(item)}
                  className={`flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-left ${i === idx ? "bg-primary-50" : ""}`}
                >
                  {Icon && <Icon className="h-4 w-4 text-primary-600" aria-hidden />}
                  <span className="flex-1">
                    <span className="block text-sm font-medium text-ink">{item.label}</span>
                    {item.hint && <span className="block text-xs text-ink-3">{item.hint}</span>}
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      </div>
    </div>
  );
}
