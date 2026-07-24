import { useEffect, useState } from "react";
import { api, ApiError } from "../lib/api";
import type { Account } from "../lib/types";
import { PageHeader, cardClass, inputClass, primaryBtn, rowClass, titleClass } from "../components/ui";

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
    <div className="min-h-[calc(100vh-3.5rem)] bg-app-light dark:bg-app-dark">
      <PageHeader title="Accounts" />
      <div className="max-w-3xl mx-auto px-6 py-6">
        <section className={`${cardClass} mb-6`}>
          <h2 className={`${titleClass} mb-3`}>Create account</h2>
          <form onSubmit={createAccount} className="space-y-2">
            <input
              className={inputClass}
              placeholder="Username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
            />
            <input
              className={inputClass}
              placeholder="Password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
            <select
              className={inputClass}
              value={role}
              onChange={(e) => setRole(e.target.value as "instructor" | "admin")}
            >
              <option value="instructor">instructor</option>
              <option value="admin">admin</option>
            </select>
            {error && <p className="text-sm text-red-600 dark:text-red-400">{error}</p>}
            <button className={primaryBtn}>Create account</button>
          </form>
        </section>

        {accounts.length === 0 ? (
          <p className="text-sm text-zinc-500 dark:text-zinc-400">No accounts yet.</p>
        ) : (
          <ul className="space-y-2">
            {accounts.map((a) => (
              <li key={a.id} className={`${rowClass} flex items-center justify-between gap-2`}>
                <div className="min-w-0">
                  <p className="text-zinc-800 dark:text-zinc-200 font-medium">
                    {a.username} <span className="text-xs text-zinc-400 dark:text-zinc-500">({a.role})</span>
                    {!a.is_active && (
                      <span className="ml-2 px-2 py-0.5 text-xs font-medium rounded-full bg-zinc-500/15 text-zinc-600 dark:text-zinc-400">
                        deactivated
                      </span>
                    )}
                  </p>
                </div>
                <button
                  onClick={() => toggleActive(a)}
                  className={
                    a.is_active
                      ? "px-3 py-1.5 border border-red-300 dark:border-red-500/30 text-red-600 dark:text-red-400 rounded-lg text-xs font-medium hover:bg-red-500/10 shrink-0"
                      : "px-3 py-1.5 border border-zinc-300 dark:border-white/10 text-zinc-700 dark:text-zinc-300 rounded-lg text-xs font-medium hover:bg-black/[0.03] dark:hover:bg-white/5 shrink-0"
                  }
                >
                  {a.is_active ? "Deactivate" : "Reactivate"}
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
