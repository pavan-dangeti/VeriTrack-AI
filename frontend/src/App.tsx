import { lazy, Suspense, type ComponentType } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AuthProvider } from "./auth/AuthContext";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { ToastProvider } from "./components/ui/toast";
import { Skeleton } from "./components/ui/kit";
import { DashboardLayout } from "./layouts/DashboardLayout";
import { AccessDeniedPage, LoginPage } from "./pages/Login";
import { RequireAuth, RequireRole } from "./routes/guards";

const qc = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      refetchOnWindowFocus: false,
      staleTime: 0, // cached data renders instantly, then revalidates in the background
      gcTime: 5 * 60_000,
    },
  },
});

/** Route-level code splitting keeps the first load small. */
function page<T extends Record<string, unknown>>(loader: () => Promise<T>, name: keyof T) {
  return lazy(async () => ({ default: (await loader())[name] as ComponentType<Record<string, unknown>> }));
}

const DashboardPage = page(() => import("./pages/Dashboard"), "DashboardPage");
const EmployeeRepositoryPage = page(() => import("./pages/EmployeeRepository"), "EmployeeRepositoryPage");
const GetsUploadsPage = page(() => import("./pages/GetsUploads"), "GetsUploadsPage");
const SheetReviewPage = page(() => import("./pages/SheetReview"), "SheetReviewPage");
const AnalysisResultsPage = page(() => import("./pages/AnalysisResults"), "AnalysisResultsPage");
const LeaveRegisterPage = page(() => import("./pages/LeaveRegister"), "LeaveRegisterPage");
const ReportsPage = page(() => import("./pages/Reports"), "ReportsPage");
const AuditLogsPage = page(() => import("./pages/AuditLogs"), "AuditLogsPage");
const ManageUsersPage = page(() => import("./pages/ManageUsers"), "ManageUsersPage");
const AccountSettingsPage = page(() => import("./pages/Settings"), "AccountSettingsPage");
const SystemSettingsPage = page(() => import("./pages/Settings"), "SystemSettingsPage");
const DirectoryPage = page(() => import("./pages/People"), "DirectoryPage");
const HrTeamPage = page(() => import("./pages/People"), "HrTeamPage");
const EmployeeDataPage = page(() => import("./pages/HrViews"), "EmployeeDataPage");
const GetsSheetsPage = page(() => import("./pages/HrViews"), "GetsSheetsPage");
const EmployeeDetailPage = page(() => import("./pages/Profile"), "EmployeeDetailPage");
const MyProfilePage = page(() => import("./pages/Profile"), "MyProfilePage");
const UserProfilePage = page(() => import("./pages/Profile"), "UserProfilePage");
const AnalyticsPage = page(() => import("./pages/Analytics"), "AnalyticsPage");

/** Routes + app shell; the caller provides the QueryClient (a fresh one per test). */
export function AppRoutes() {
  return (
    <>
      <ErrorBoundary>
        <ToastProvider>
          <AuthProvider>
            <Suspense fallback={<Skeleton rows={6} />}>
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
                      <Route
                        path="/all-employees"
                        element={
                          <EmployeeRepositoryPage
                            readOnly
                            title="All Employee Repositories"
                            subtitle="Cross-manager view (read-only). Flags show records needing review."
                          />
                        }
                      />
                      <Route path="/all-uploads" element={<GetsUploadsPage crossManager />} />
                      <Route path="/all-reports" element={<ReportsPage crossManager />} />
                      <Route path="/directory" element={<DirectoryPage />} />
                      <Route path="/people/:userId" element={<UserProfilePage />} />
                      <Route path="/employees" element={<EmployeeRepositoryPage />} />
                      <Route path="/employees/:employeeId" element={<EmployeeDetailPage />} />
                      <Route path="/gets" element={<GetsUploadsPage />} />
                      <Route path="/review/:batchId/:fileId" element={<SheetReviewPage />} />
                      <Route path="/analysis/:batchId" element={<AnalysisResultsPage />} />
                      <Route path="/leaves" element={<LeaveRegisterPage />} />
                      <Route path="/reports" element={<ReportsPage />} />
                      <Route path="/hr-team" element={<HrTeamPage />} />
                      <Route path="/employee-data" element={<EmployeeDataPage />} />
                      <Route path="/gets-sheets" element={<GetsSheetsPage />} />
                    </Route>
                  </Route>
                </Route>

                <Route path="*" element={<Navigate to="/dashboard" replace />} />
              </Routes>
            </Suspense>
          </AuthProvider>
        </ToastProvider>
      </ErrorBoundary>
    </>
  );
}

export default function App() {
  return (
    <QueryClientProvider client={qc}>
      <BrowserRouter>
        <AppRoutes />
      </BrowserRouter>
    </QueryClientProvider>
  );
}
