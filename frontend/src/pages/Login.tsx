import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { ApiError } from "../lib/api";
import { useTheme } from "../theme/ThemeContext";

export function LoginPage() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const { preference, setPreference } = useTheme();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await login(username, password);
      navigate("/");
    } catch (err) {
      setError(err instanceof ApiError ? "Invalid username or password" : "Login failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-app-light dark:bg-app-dark">
      <select
        value={preference}
        onChange={(e) => setPreference(e.target.value as "system" | "light" | "dark")}
        className="fixed top-4 right-4 text-sm bg-white dark:bg-white/5 text-zinc-700 dark:text-zinc-200 border border-zinc-300 dark:border-white/10 rounded-lg px-2 py-1"
      >
        <option value="system">System</option>
        <option value="light">Light</option>
        <option value="dark">Dark</option>
      </select>
      <form onSubmit={onSubmit} className="w-full max-w-sm bg-surface-light dark:bg-surface-dark border border-zinc-200 dark:border-transparent rounded-2xl p-6 shadow-sm">
        <h1 className="text-lg font-semibold text-zinc-900 dark:text-zinc-100 mb-4">Sign in</h1>
        {error && <p className="text-sm text-red-600 dark:text-red-400 mb-3">{error}</p>}
        <label className="block text-sm text-zinc-700 dark:text-zinc-300 mb-1">Username</label>
        <input
          className="w-full mb-3 px-3 py-2 border border-zinc-300 dark:border-white/10 rounded-lg bg-white dark:bg-white/5 text-zinc-900 dark:text-zinc-100"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          autoFocus
        />
        <label className="block text-sm text-zinc-700 dark:text-zinc-300 mb-1">Password</label>
        <input
          type="password"
          className="w-full mb-4 px-3 py-2 border border-zinc-300 dark:border-white/10 rounded-lg bg-white dark:bg-white/5 text-zinc-900 dark:text-zinc-100"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
        <button
          type="submit"
          disabled={busy}
          className="w-full bg-blue-600 hover:bg-blue-500 dark:bg-blue-500 dark:hover:bg-blue-400 text-white rounded-lg py-2 text-sm font-medium disabled:opacity-50"
        >
          {busy ? "Signing in…" : "Sign in"}
        </button>
        <p className="text-xs text-zinc-400 dark:text-zinc-500 mt-4">
          Test logins: admin/admin123, instructor/instruct123
        </p>
      </form>
    </div>
  );
}
