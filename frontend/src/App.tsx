import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AuthProvider } from "./auth/AuthContext";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { ToastProvider } from "./components/ui/toast";
import { DashboardLayout } from "./layouts/DashboardLayout";
import { AccessDeniedPage, LoginPage } from "./pages/Login";
import { RequireAuth, RequireRole } from "./routes/guards";

const qc = new QueryClient({
  defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } },
});

import { DashboardPage } from "./pages/Dashboard";
import { EmployeeRepositoryPage } from "./pages/EmployeeRepository";
import { GetsUploadsPage } from "./pages/GetsUploads";
import { ReportsPage } from "./pages/Reports";
import { AuditLogsPage } from "./pages/AuditLogs";
import { ManageUsersPage } from "./pages/ManageUsers";
import { AccountSettingsPage, SystemSettingsPage } from "./pages/Settings";
import { DirectoryPage, HrTeamPage } from "./pages/People";
import { EmployeeDataPage, GetsSheetsPage } from "./pages/HrViews";
import { EmployeeDetailPage, MyProfilePage, UserProfilePage } from "./pages/Profile";
import { AnalyticsPage } from "./pages/Analytics";

export function AppRoutes() {
  return (
    <QueryClientProvider client={qc}>
      <ErrorBoundary>
        <ToastProvider>
          <AuthProvider>
            <Routes>
              <Route path="/login" element={<LoginPage />} />
              <Route path="/access-denied" element={<AccessDeniedPage />} />

              <Route element={<RequireAuth />}>
                <Route element={<DashboardLayout />}>
                  <Route path="/dashboard" element={<DashboardPage />} />
                  <Route path="/account" element={<AccountSettingsPage />} />
                  <Route path="/profile" element={<MyProfilePage />} />

                  {/* Role-enforced subtree: nav.ts is the single source of truth */}
                  <Route element={<RequireRole />}>
                    <Route path="/analytics" element={<AnalyticsPage />} />
                    <Route path="/users" element={<ManageUsersPage />} />
                    <Route path="/settings" element={<SystemSettingsPage />} />
                    <Route path="/audit-logs" element={<AuditLogsPage />} />
                    <Route path="/all-employees" element={
                      <EmployeeRepositoryPage
                        readOnly
                        title="All Employee Repositories"
                        subtitle="Cross-manager view (read-only). Flags show records needing review."
                      />
                    } />
                    <Route path="/all-uploads" element={<GetsUploadsPage crossManager />} />
                    <Route path="/all-reports" element={<ReportsPage crossManager />} />
                    <Route path="/directory" element={<DirectoryPage />} />
                    <Route path="/people/:userId" element={<UserProfilePage />} />
                    <Route path="/employees" element={<EmployeeRepositoryPage />} />
                    <Route path="/employees/:employeeId" element={<EmployeeDetailPage />} />
                    <Route path="/gets" element={<GetsUploadsPage />} />
                    <Route path="/reports" element={<ReportsPage />} />
                    <Route path="/hr-team" element={<HrTeamPage />} />
                    <Route path="/employee-data" element={<EmployeeDataPage />} />
                    <Route path="/gets-sheets" element={<GetsSheetsPage />} />
                  </Route>
                </Route>
              </Route>

            <Route path="*" element={<Navigate to="/dashboard" replace />} />
            </Routes>
          </AuthProvider>
        </ToastProvider>
      </ErrorBoundary>
    </QueryClientProvider>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <AppRoutes />
    </BrowserRouter>
  );
}
