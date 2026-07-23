import { Navigate, Route, Routes } from "react-router-dom";
import { useAuth } from "./auth/AuthContext";
import { NavBar } from "./components/NavBar";
import { LoginPage } from "./pages/Login";
import { DashboardPage } from "./pages/Dashboard";
import { CoursePage } from "./pages/CoursePage";
import { AssignmentPage } from "./pages/AssignmentPage";
import { AssignmentBreakdownPage } from "./pages/AssignmentBreakdownPage";
import { AssessmentPage } from "./pages/AssessmentPage";
import { ReviewPage } from "./pages/ReviewPage";
import { SettingsPage } from "./pages/Settings";
import { AccountsPage } from "./pages/AccountsPage";

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
          path="/admin/accounts"
          element={
            <RequireAdmin>
              <AccountsPage />
            </RequireAdmin>
          }
        />
      </Routes>
    </div>
  );
}
