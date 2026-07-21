import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { useTheme } from "../theme/ThemeContext";

export function NavBar() {
  const { role, logout } = useAuth();
  const { preference, setPreference } = useTheme();
  const navigate = useNavigate();

  return (
    <nav className="flex items-center justify-between px-6 py-3 bg-white dark:bg-gray-900 border-b border-gray-200 dark:border-gray-800">
      <div className="flex items-center gap-6">
        <Link to="/" className="font-semibold text-gray-900 dark:text-gray-100">
          Proteus (Dual RAG Grading)
        </Link>
        <Link to="/" className="text-sm text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-gray-100">
          Courses
        </Link>
        {role && (
          <Link to="/settings" className="text-sm text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-gray-100">
            Settings
          </Link>
        )}
      </div>
      <div className="flex items-center gap-3">
        <select
          value={preference}
          onChange={(e) => setPreference(e.target.value as "system" | "light" | "dark")}
          className="text-sm bg-white dark:bg-gray-800 text-gray-700 dark:text-gray-200 border border-gray-300 dark:border-gray-700 rounded px-2 py-1"
        >
          <option value="system">System</option>
          <option value="light">Light</option>
          <option value="dark">Dark</option>
        </select>
        {role && (
          <button
            onClick={() => {
              logout();
              navigate("/login");
            }}
            className="text-sm text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-gray-100"
          >
            Log out
          </button>
        )}
      </div>
    </nav>
  );
}
