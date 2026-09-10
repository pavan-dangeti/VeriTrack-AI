import type { Role } from "../auth/AuthContext";

export interface NavItem {
  path: string;
  label: string;
  roles: Role[];
  /** Allowed by the guard but not shown in the sidebar (drill-down routes). */
  hidden?: boolean;
  /** Named group the sidebar renders under a heading; drives section order. */
  section?: string;
}

/**
 * Single source of truth mapping routes to roles. The sidebar renders FROM
 * this (role-aware per locked requirement), and the route guard ENFORCES it —
 * hidden link and blocked URL stay in lockstep by construction. Sections group
 * the sidebar into distinct tiers; ordering here is the ordering everywhere.
 * "Account" sits at the bottom on its own, visually separated from the
 * operational pages (standard SaaS convention).
 */
export const NAV_ITEMS: NavItem[] = [
  // Overview
  { path: "/dashboard", label: "Dashboard", roles: ["MASTER_ADMIN", "EXECUTIVE", "MANAGER", "HR"], section: "Overview" },
  { path: "/analytics", label: "Analytics", roles: ["MASTER_ADMIN", "EXECUTIVE", "MANAGER", "HR"], section: "Overview" },

  // Workspace / operational
  { path: "/users", label: "Manage Users", roles: ["MASTER_ADMIN"], section: "Workspace" },
  { path: "/all-uploads", label: "All GETS Uploads", roles: ["MASTER_ADMIN"], section: "Workspace" },
  { path: "/all-employees", label: "All Employee Repositories", roles: ["MASTER_ADMIN", "EXECUTIVE"], section: "Workspace" },
  { path: "/employees", label: "Employee Repository", roles: ["MANAGER"], section: "Workspace" },
  { path: "/gets", label: "GETS Uploads", roles: ["MANAGER"], section: "Workspace" },
  { path: "/employee-data", label: "Employee Data", roles: ["HR"], section: "Workspace" },
  { path: "/gets-sheets", label: "Monthly GETS Sheets", roles: ["HR"], section: "Workspace" },
  { path: "/all-reports", label: "All Reports", roles: ["MASTER_ADMIN", "EXECUTIVE"], section: "Workspace" },
  { path: "/reports", label: "Reports & History", roles: ["MANAGER"], section: "Workspace" },
  { path: "/directory", label: "Manager & HR Directory", roles: ["EXECUTIVE"], section: "Workspace" },
  { path: "/hr-team", label: "My HR Team", roles: ["MANAGER"], section: "Workspace" },

  // Admin (Master Admin only)
  { path: "/settings", label: "System Settings", roles: ["MASTER_ADMIN"], section: "Admin" },
  { path: "/audit-logs", label: "Audit Logs", roles: ["MASTER_ADMIN"], section: "Admin" },

  // Account — bottom, on its own tier
  { path: "/profile", label: "Profile", roles: ["MASTER_ADMIN", "EXECUTIVE", "MANAGER", "HR"], section: "Account" },
  { path: "/account", label: "Account Settings", roles: ["MASTER_ADMIN", "EXECUTIVE", "MANAGER", "HR"], section: "Account" },

  // Drill-down (no sidebar entry; reached by clicking rows)
  { path: "/people", label: "User Profile", roles: ["MASTER_ADMIN", "EXECUTIVE", "MANAGER"], hidden: true },
];

export const NAV_SECTIONS = ["Overview", "Workspace", "Admin", "Account"] as const;

export function navFor(role: Role): NavItem[] {
  return NAV_ITEMS.filter((item) => !item.hidden && item.roles.includes(role));
}

export function roleCanAccess(role: Role, path: string): boolean {
  const exact = NAV_ITEMS.find((n) => n.path === path);
  if (exact) return exact.roles.includes(role);
  // Prefix match for nested routes (e.g. /gets/:batchId)
  const prefix = NAV_ITEMS.find((n) => path.startsWith(n.path + "/"));
  return prefix ? prefix.roles.includes(role) : false;
}

export const HOME_FOR_ROLE: Record<Role, string> = {
  MASTER_ADMIN: "/dashboard",
  EXECUTIVE: "/dashboard",
  MANAGER: "/dashboard",
  HR: "/dashboard",
};
