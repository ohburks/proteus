import { useEffect, useState } from "react";
import { api, ApiError } from "../lib/api";
import type { Account } from "../lib/types";

export function AccountsPage() {
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<"instructor" | "admin">("instructor");
  const [error, setError] = useState<string | null>(null);

  function refresh() {
    api.get<Account[]>("/api/accounts").then(setAccounts);
  }

  useEffect(refresh, []);

  async function createAccount(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (!username.trim() || !password.trim()) {
      setError("Username and password are required.");
      return;
    }
    try {
      await api.post("/api/accounts", { username, password, role });
      setUsername("");
      setPassword("");
      setRole("instructor");
      refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to create account");
    }
  }

  async function toggleActive(account: Account) {
    if (account.is_active && !confirm(`Deactivate "${account.username}"? They won't be able to log in.`)) return;
    try {
      await api.put(`/api/accounts/${account.id}/status`, { is_active: !account.is_active });
      refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to update account");
    }
  }

  return (
    <div className="max-w-2xl mx-auto px-6 py-8 bg-app-light dark:bg-app-dark min-h-[calc(100vh-3.5rem)]">
      <h1 className="text-xl font-semibold text-zinc-900 dark:text-zinc-100 mb-6">Accounts</h1>

      <section className="bg-surface-light dark:bg-surface-dark border border-zinc-200 dark:border-transparent rounded-2xl p-5 mb-6">
        <h2 className="text-sm font-semibold text-blue-600 dark:text-blue-400 mb-3">Create account</h2>
        <form onSubmit={createAccount} className="space-y-2">
          <input
            className="w-full px-3 py-2 border border-zinc-300 dark:border-white/10 rounded-lg bg-white dark:bg-white/5 text-zinc-900 dark:text-zinc-100"
            placeholder="Username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
          />
          <input
            className="w-full px-3 py-2 border border-zinc-300 dark:border-white/10 rounded-lg bg-white dark:bg-white/5 text-zinc-900 dark:text-zinc-100"
            placeholder="Password"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
          <select
            className="w-full px-3 py-2 border border-zinc-300 dark:border-white/10 rounded-lg bg-white dark:bg-white/5 text-zinc-900 dark:text-zinc-100"
            value={role}
            onChange={(e) => setRole(e.target.value as "instructor" | "admin")}
          >
            <option value="instructor">instructor</option>
            <option value="admin">admin</option>
          </select>
          {error && <p className="text-sm text-red-600 dark:text-red-400">{error}</p>}
          <button className="px-4 py-2 bg-blue-600 hover:bg-blue-500 dark:bg-blue-500 dark:hover:bg-blue-400 text-white rounded-lg text-sm font-medium">
            Create account
          </button>
        </form>
      </section>

      <ul className="divide-y divide-zinc-200 dark:divide-white/5 bg-surface-light dark:bg-surface-dark border border-zinc-200 dark:border-transparent rounded-2xl overflow-hidden">
        {accounts.map((a) => (
          <li key={a.id} className="flex items-center justify-between px-4 py-3">
            <div>
              <p className="text-zinc-800 dark:text-zinc-200 font-medium">
                {a.username} <span className="text-xs text-zinc-400 dark:text-zinc-500">({a.role})</span>
              </p>
              {!a.is_active && (
                <span className="px-2 py-0.5 text-xs font-medium rounded-full bg-zinc-500/15 text-zinc-600 dark:text-zinc-400">
                  deactivated
                </span>
              )}
            </div>
            <button
              onClick={() => toggleActive(a)}
              className={
                a.is_active
                  ? "px-3 py-1 border border-red-300 dark:border-red-500/30 text-red-600 dark:text-red-400 rounded-lg text-xs font-medium hover:bg-red-500/10"
                  : "px-3 py-1 border border-zinc-300 dark:border-white/10 text-zinc-700 dark:text-zinc-300 rounded-lg text-xs font-medium hover:bg-black/[0.03] dark:hover:bg-white/5"
              }
            >
              {a.is_active ? "Deactivate" : "Reactivate"}
            </button>
          </li>
        ))}
        {accounts.length === 0 && <li className="px-4 py-3 text-zinc-500 dark:text-zinc-400">No accounts yet.</li>}
      </ul>
    </div>
  );
}
