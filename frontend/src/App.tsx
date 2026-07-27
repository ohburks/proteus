import { lazy, Suspense } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { useAuth } from "./auth/AuthContext";
import { NavBar } from "./components/NavBar";

const LoginPage = lazy(() => import("./pages/Login").then((module) => ({ default: module.LoginPage })));
const DashboardPage = lazy(() =>
  import("./pages/Dashboard").then((module) => ({ default: module.DashboardPage })),
);
const CoursePage = lazy(() =>
  import("./pages/CoursePage").then((module) => ({ default: module.CoursePage })),
);
const AssignmentPage = lazy(() =>
  import("./pages/AssignmentPage").then((module) => ({ default: module.AssignmentPage })),
);
const AssignmentBreakdownPage = lazy(() =>
  import("./pages/AssignmentBreakdownPage").then((module) => ({
    default: module.AssignmentBreakdownPage,
  })),
);
const AssessmentPage = lazy(() =>
  import("./pages/AssessmentPage").then((module) => ({ default: module.AssessmentPage })),
);
const ReviewPage = lazy(() =>
  import("./pages/ReviewPage").then((module) => ({ default: module.ReviewPage })),
);
const SettingsPage = lazy(() =>
  import("./pages/Settings").then((module) => ({ default: module.SettingsPage })),
);
const AccountsPage = lazy(() =>
  import("./pages/AccountsPage").then((module) => ({ default: module.AccountsPage })),
);
const LibraryPage = lazy(() =>
  import("./pages/LibraryPage").then((module) => ({ default: module.LibraryPage })),
);
const StudentHistoryPage = lazy(() =>
  import("./pages/StudentHistoryPage").then((module) => ({ default: module.StudentHistoryPage })),
);
const AuditLogPage = lazy(() =>
  import("./pages/AuditLogPage").then((module) => ({ default: module.AuditLogPage })),
);

function RequireAuth({ children }: { children: React.ReactNode }) {
  const { token } = useAuth();
  if (!token) return <Navigate to="/login" replace />;
  return <>{children}</>;
}

function RequireAdmin({ children }: { children: React.ReactNode }) {
  const { token, role } = useAuth();
  if (!token) return <Navigate to="/login" replace />;
  if (role !== "admin") return <Navigate to="/" replace />;
  return <>{children}</>;
}

export default function App() {
  const { token } = useAuth();
  return (
    <div className="min-h-screen bg-app-light dark:bg-app-dark">
      {token && <NavBar />}
      <Suspense
        fallback={
          <div className="mx-auto max-w-5xl px-6 py-12 text-sm text-zinc-500 dark:text-zinc-400">
            Loading…
          </div>
        }
      >
        <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route
          path="/"
          element={
            <RequireAuth>
              <DashboardPage />
            </RequireAuth>
          }
        />
        <Route
          path="/courses/:courseId"
          element={
            <RequireAuth>
              <CoursePage />
            </RequireAuth>
          }
        />
        <Route
          path="/assignments/:assignmentId"
          element={
            <RequireAuth>
              <AssignmentPage />
            </RequireAuth>
          }
        />
        <Route
          path="/assignments/:assignmentId/breakdown"
          element={
            <RequireAuth>
              <AssignmentBreakdownPage />
            </RequireAuth>
          }
        />
        <Route
          path="/assessments/:assessmentId"
          element={
            <RequireAuth>
              <AssessmentPage />
            </RequireAuth>
          }
        />
        <Route
          path="/assessments/:assessmentId/criteria/:criterionId"
          element={
            <RequireAuth>
              <ReviewPage />
            </RequireAuth>
          }
        />
        <Route
          path="/settings"
          element={
            <RequireAuth>
              <SettingsPage />
            </RequireAuth>
          }
        />
        <Route
          path="/library"
          element={
            <RequireAuth>
              <LibraryPage />
            </RequireAuth>
          }
        />
        <Route
          path="/students/:studentId/history"
          element={
            <RequireAuth>
              <StudentHistoryPage />
            </RequireAuth>
          }
        />
        <Route
          path="/admin/accounts"
          element={
            <RequireAdmin>
              <AccountsPage />
            </RequireAdmin>
          }
        />
        <Route
          path="/admin/audit"
          element={
            <RequireAdmin>
              <AuditLogPage />
            </RequireAdmin>
          }
        />
        </Routes>
      </Suspense>
    </div>
  );
}
