import { useEffect, useState } from "react";
import { api, ApiError } from "../lib/api";
import type { Account } from "../lib/types";
import {
  Chip,
  OverflowMenu,
  PageHeader,
  Tabs,
  cardClass,
  helpClass,
  inputClass,
  labelClass,
  primaryBtn,
  rowClass,
} from "../components/ui";

type AccountTab = "active" | "deactivated";

export function AccountsPage() {
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<"instructor" | "admin">("instructor");
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<AccountTab>("active");
  const [showNewAccount, setShowNewAccount] = useState(false);

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
      setShowNewAccount(false);
      setActiveTab("active");
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

  const activeAccounts = accounts.filter((account) => account.is_active);
  const deactivatedAccounts = accounts.filter((account) => !account.is_active);
  const visibleAccounts = activeTab === "active" ? activeAccounts : deactivatedAccounts;
  const instructorCount = accounts.filter((account) => account.role === "instructor").length;
  const adminCount = accounts.length - instructorCount;

  return (
    <div className="min-h-[calc(100vh-3.5rem)] bg-app-light dark:bg-app-dark">
      <PageHeader
        title="Accounts"
        subtitle={`${activeAccounts.length} active · ${instructorCount} instructor${
          instructorCount === 1 ? "" : "s"
        } · ${adminCount} admin${adminCount === 1 ? "" : "s"}`}
      />
      <div className="max-w-3xl mx-auto px-6 py-6">
        <div className="mb-4">
          <Chip active={showNewAccount} onClick={() => setShowNewAccount((visible) => !visible)}>
            <span className="text-base leading-none">＋</span> New account
          </Chip>
        </div>

        {showNewAccount && (
          <form onSubmit={createAccount} className={`${cardClass} mb-4`}>
            <p className={`${helpClass} mb-4`}>
              Instructor accounts own courses and grading data. Admin accounts manage access across the
              workspace.
            </p>
            <div className="grid gap-3 sm:grid-cols-2">
              <div>
                <label htmlFor="new-account-username" className={labelClass}>
                  Username
                </label>
                <input
                  id="new-account-username"
                  className={inputClass}
                  placeholder="e.g. morgan"
                  autoComplete="off"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                />
              </div>
              <div>
                <label htmlFor="new-account-password" className={labelClass}>
                  Temporary password
                </label>
                <input
                  id="new-account-password"
                  className={inputClass}
                  placeholder="Set an initial password"
                  type="password"
                  autoComplete="new-password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                />
              </div>
              <div>
                <label htmlFor="new-account-role" className={labelClass}>
                  Role
                </label>
                <select
                  id="new-account-role"
                  className={inputClass}
                  value={role}
                  onChange={(e) => setRole(e.target.value as "instructor" | "admin")}
                >
                  <option value="instructor">Instructor</option>
                  <option value="admin">Admin</option>
                </select>
              </div>
              <div className="flex items-end">
                <button className={`${primaryBtn} w-full sm:w-auto`}>Create account</button>
              </div>
            </div>
          </form>
        )}

        {error && <p className="text-sm text-red-600 dark:text-red-400 mb-4">{error}</p>}

        <Tabs
          className="mb-4"
          active={activeTab}
          onChange={setActiveTab}
          tabs={[
            { key: "active", label: `Active (${activeAccounts.length})` },
            { key: "deactivated", label: `Deactivated (${deactivatedAccounts.length})` },
          ]}
        />

        {visibleAccounts.length === 0 ? (
          <p className="text-sm text-zinc-500 dark:text-zinc-400">
            {activeTab === "active" ? "No active accounts." : "No deactivated accounts."}
          </p>
        ) : (
          <ul className="space-y-2">
            {visibleAccounts.map((account) => (
              <li key={account.id} className={`${rowClass} flex items-center justify-between gap-3`}>
                <div className="min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <p className="text-zinc-800 dark:text-zinc-200 font-medium truncate">
                      {account.username}
                    </p>
                    <span
                      className={`px-2.5 py-0.5 text-xs font-medium rounded-full ${
                        account.role === "admin"
                          ? "bg-purple-500/15 text-purple-700 dark:text-purple-400"
                          : "bg-blue-500/15 text-blue-700 dark:text-blue-400"
                      }`}
                    >
                      {account.role}
                    </span>
                    {!account.is_active && (
                      <span className="px-2.5 py-0.5 text-xs font-medium rounded-full bg-zinc-500/15 text-zinc-600 dark:text-zinc-400">
                        deactivated
                      </span>
                    )}
                  </div>
                  <p className="mt-1 text-xs text-zinc-400 dark:text-zinc-500">
                    Created {new Date(account.created_at).toLocaleDateString()}
                  </p>
                </div>
                {account.is_active ? (
                  <OverflowMenu
                    items={[{ label: "Deactivate account", onClick: () => toggleActive(account), danger: true }]}
                  />
                ) : (
                  <button
                    onClick={() => toggleActive(account)}
                    className="px-3 py-1.5 border border-zinc-300 dark:border-white/10 text-zinc-700 dark:text-zinc-300 rounded-lg text-xs font-medium hover:bg-black/[0.03] dark:hover:bg-white/5 shrink-0"
                  >
                    Reactivate
                  </button>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
