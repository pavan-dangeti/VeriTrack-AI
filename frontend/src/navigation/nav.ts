import type { LucideIcon } from "lucide-react";
import {
  BarChart3,
  CalendarCheck2,
  FileSpreadsheet,
  FileText,
  FolderKanban,
  LayoutDashboard,
  ScrollText,
  Settings,
  ShieldCheck,
  UserCircle2,
  Users,
  UsersRound,
} from "lucide-react";
import type { Role } from "../auth/AuthContext";

export interface NavItem {
  path: string;
  label: string;
  roles: Role[];
  /** Allowed by the guard but not shown in the sidebar (drill-down routes). */
  hidden?: boolean;
  /** Named group the sidebar renders under a heading; drives section order. */
  section?: string;
  icon?: LucideIcon;
  /** One-line hint shown in the command palette. */
  hint?: string;
}

const ALL: Role[] = ["MASTER_ADMIN", "EXECUTIVE", "MANAGER", "HR"];

/**
 * Single source of truth mapping routes to roles: the sidebar renders from it and the route
 * guard enforces it, so a hidden link and a blocked URL can't drift apart.
 */
const NAV_ITEMS: NavItem[] = [
  { path: "/dashboard", label: "Dashboard", roles: ALL, section: "Overview", icon: LayoutDashboard, hint: "Key numbers at a glance" },
  { path: "/analytics", label: "Analytics", roles: ALL, section: "Overview", icon: BarChart3, hint: "Trends, email outcomes, per-manager views" },

  { path: "/users", label: "Manage Users", roles: ["MASTER_ADMIN"], section: "Workspace", icon: Users, hint: "Create and disable accounts" },
  { path: "/all-uploads", label: "All GETS Uploads", roles: ["MASTER_ADMIN"], section: "Workspace", icon: FolderKanban, hint: "Every manager's GETS batches" },
  { path: "/all-employees", label: "All Employee Repositories", roles: ["MASTER_ADMIN", "EXECUTIVE"], section: "Workspace", icon: UsersRound },
  { path: "/employees", label: "Employee Repository", roles: ["MANAGER"], section: "Workspace", icon: UsersRound, hint: "Your team's master data" },
  { path: "/gets", label: "GETS Uploads", roles: ["MANAGER"], section: "Workspace", icon: FileSpreadsheet, hint: "Upload timesheets, review extraction, analyze" },
  { path: "/leaves", label: "Company Leave Register", roles: ALL, section: "Workspace", icon: CalendarCheck2, hint: "Company-side leave records" },
  { path: "/employee-data", label: "Employee Data", roles: ["HR"], section: "Workspace", icon: UsersRound },
  { path: "/gets-sheets", label: "Monthly GETS Sheets", roles: ["HR"], section: "Workspace", icon: FileSpreadsheet },
  { path: "/all-reports", label: "All Reports", roles: ["MASTER_ADMIN", "EXECUTIVE"], section: "Workspace", icon: FileText },
  { path: "/reports", label: "Reports & History", roles: ["MANAGER"], section: "Workspace", icon: FileText, hint: "Analysis runs, PDFs and Excel reports" },
  { path: "/directory", label: "Manager & HR Directory", roles: ["EXECUTIVE"], section: "Workspace", icon: Users },
  { path: "/hr-team", label: "My HR Team", roles: ["MANAGER"], section: "Workspace", icon: Users },

  { path: "/settings", label: "System Settings", roles: ["MASTER_ADMIN"], section: "Admin", icon: Settings },
  { path: "/audit-logs", label: "Audit Logs", roles: ["MASTER_ADMIN"], section: "Admin", icon: ScrollText },

  { path: "/profile", label: "Profile", roles: ALL, section: "Account", icon: UserCircle2 },
  { path: "/account", label: "Account Settings", roles: ALL, section: "Account", icon: ShieldCheck },

  // Drill-down (no sidebar entry; reached by clicking rows)
  { path: "/people", label: "User Profile", roles: ["MASTER_ADMIN", "EXECUTIVE", "MANAGER"], hidden: true },
  { path: "/review", label: "Sheet Review", roles: ALL, hidden: true },
  { path: "/analysis", label: "Analysis Results", roles: ["MASTER_ADMIN", "EXECUTIVE", "MANAGER"], hidden: true },
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

