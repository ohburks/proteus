import { Link, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { useTheme } from "../theme/ThemeContext";

export function NavBar() {
  const { role, logout } = useAuth();
  const { preference, setPreference } = useTheme();
  const navigate = useNavigate();
  const location = useLocation();

  function navLinkClass(active: boolean) {
    return `text-sm px-3 py-1.5 rounded-full transition-colors ${
      active
        ? "bg-black/5 dark:bg-white/10 text-zinc-900 dark:text-zinc-100 font-medium"
        : "text-zinc-500 dark:text-zinc-400 hover:text-zinc-900 dark:hover:text-zinc-100"
    }`;
  }

  return (
    <nav className="flex items-center justify-between px-6 py-3 bg-surface-light dark:bg-app-dark border-b border-zinc-200 dark:border-transparent">
      <div className="flex items-center gap-2">
        <Link to="/" className="font-semibold text-zinc-900 dark:text-zinc-100 mr-4">
          Proteus <span className="text-blue-600 dark:text-blue-400">(Dual RAG Grading)</span>
        </Link>
        <Link to="/" className={navLinkClass(location.pathname === "/")}>
          Courses
        </Link>
        {role && (
          <Link to="/library" className={navLinkClass(location.pathname === "/library")}>
            Library
          </Link>
        )}
        {role && (
          <Link to="/settings" className={navLinkClass(location.pathname === "/settings")}>
            Settings
          </Link>
        )}
      </div>
      <div className="flex items-center gap-3">
        <select
          value={preference}
          onChange={(e) => setPreference(e.target.value as "system" | "light" | "dark")}
          className="text-sm bg-white dark:bg-white/5 text-zinc-700 dark:text-zinc-200 border border-zinc-300 dark:border-white/10 rounded-lg px-2 py-1"
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
            className="text-sm text-zinc-500 dark:text-zinc-400 hover:text-zinc-900 dark:hover:text-zinc-100"
          >
            Log out
          </button>
        )}
      </div>
    </nav>
  );
}
