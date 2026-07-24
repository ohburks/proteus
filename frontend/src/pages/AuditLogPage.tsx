import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "../lib/api";
import type { AuditEvent, AuditEventPage } from "../lib/types";
import { PageHeader, headerBtn, inputClass, selectClass } from "../components/ui";

const PAGE_SIZE = 40;

function actionLabel(action: string): string {
  return action.replaceAll(".", " · ").replaceAll("_", " ");
}

function metadataValue(value: unknown): string {
  if (value === null) return "—";
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  return JSON.stringify(value);
}

function EventRow({ event }: { event: AuditEvent }) {
  const metadata = Object.entries(event.metadata);
  const outcomeClass =
    event.outcome === "success"
      ? "bg-green-500/15 text-green-700 dark:text-green-400"
      : event.outcome === "denied"
        ? "bg-amber-500/15 text-amber-700 dark:text-amber-400"
        : "bg-red-500/15 text-red-700 dark:text-red-400";

  return (
    <li className="bg-surface-light dark:bg-surface-dark border border-zinc-200 dark:border-transparent rounded-2xl p-4">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <p className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">
              {actionLabel(event.action)}
            </p>
            <span className={`px-2.5 py-0.5 text-xs font-medium rounded-full ${outcomeClass}`}>
              {event.outcome}
            </span>
          </div>
          <p className="mt-1 text-xs text-zinc-500 dark:text-zinc-400">
            {event.actor_username ?? "Unknown actor"}
            {event.actor_role ? ` · ${event.actor_role}` : ""}
            {event.ip_address ? ` · ${event.ip_address}` : ""}
          </p>
        </div>
        <time
          dateTime={event.occurred_at}
          className="shrink-0 text-xs text-zinc-400 dark:text-zinc-500"
          title={new Date(event.occurred_at).toLocaleString()}
        >
          {new Date(event.occurred_at).toLocaleString()}
        </time>
      </div>

      {(event.target_type || event.target_id) && (
        <p className="mt-3 text-xs text-zinc-600 dark:text-zinc-300 font-mono break-all">
          {event.target_type ?? "target"}
          {event.target_id ? ` · ${event.target_id}` : ""}
        </p>
      )}

      {metadata.length > 0 && (
        <details className="mt-3">
          <summary className="cursor-pointer text-xs text-blue-600 dark:text-blue-400">
            Event details
          </summary>
          <dl className="mt-2 grid gap-x-4 gap-y-1.5 sm:grid-cols-[max-content_1fr] text-xs">
            {metadata.map(([key, value]) => (
              <div key={key} className="contents">
                <dt className="text-zinc-400 dark:text-zinc-500">{key.replaceAll("_", " ")}</dt>
                <dd className="text-zinc-700 dark:text-zinc-300 break-all">{metadataValue(value)}</dd>
              </div>
            ))}
          </dl>
        </details>
      )}
    </li>
  );
}

export function AuditLogPage() {
  const [page, setPage] = useState<AuditEventPage | null>(null);
  const [offset, setOffset] = useState(0);
  const [action, setAction] = useState("");
  const [outcome, setOutcome] = useState("");
  const [searchDraft, setSearchDraft] = useState("");
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(() => {
    setLoading(true);
    setError(null);
    const params = new URLSearchParams({
      limit: String(PAGE_SIZE),
      offset: String(offset),
    });
    if (action) params.set("action", action);
    if (outcome) params.set("outcome", outcome);
    if (search) params.set("search", search);
    api
      .get<AuditEventPage>(`/api/audit-events?${params}`)
      .then(setPage)
      .catch((err) => setError(err instanceof ApiError ? err.message : "Failed to load audit events"))
      .finally(() => setLoading(false));
  }, [action, offset, outcome, search]);

  useEffect(refresh, [refresh]);

  function applySearch(e: React.FormEvent) {
    e.preventDefault();
    setOffset(0);
    setSearch(searchDraft.trim());
  }

  function changeAction(next: string) {
    setOffset(0);
    setAction(next);
  }

  function changeOutcome(next: string) {
    setOffset(0);
    setOutcome(next);
  }

  const first = page && page.total > 0 ? page.offset + 1 : 0;
  const last = page ? Math.min(page.offset + page.items.length, page.total) : 0;

  return (
    <div className="min-h-[calc(100vh-3.5rem)] bg-app-light dark:bg-app-dark">
      <PageHeader
        title="Security audit"
        subtitle={page ? `${page.total} event${page.total === 1 ? "" : "s"}` : "Administrator access only"}
        right={
          <button type="button" onClick={refresh} className={headerBtn}>
            Refresh
          </button>
        }
      />
      <div className="max-w-3xl mx-auto px-6 py-6">
        <div className="grid gap-2 mb-5 sm:grid-cols-[1fr_auto_auto]">
          <form onSubmit={applySearch} className="flex gap-2">
            <input
              className={inputClass}
              value={searchDraft}
              onChange={(e) => setSearchDraft(e.target.value)}
              placeholder="Search actor, target, or IP"
              aria-label="Search audit events"
            />
            <button type="submit" className={headerBtn}>
              Search
            </button>
          </form>
          <select
            className={selectClass}
            value={action}
            onChange={(e) => changeAction(e.target.value)}
            aria-label="Filter by action"
          >
            <option value="">All actions</option>
            {(page?.actions ?? []).map((item) => (
              <option key={item} value={item}>
                {actionLabel(item)}
              </option>
            ))}
          </select>
          <select
            className={selectClass}
            value={outcome}
            onChange={(e) => changeOutcome(e.target.value)}
            aria-label="Filter by outcome"
          >
            <option value="">All outcomes</option>
            <option value="success">Success</option>
            <option value="failure">Failure</option>
            <option value="denied">Denied</option>
          </select>
        </div>

        {error ? (
          <p className="text-sm text-red-600 dark:text-red-400">{error}</p>
        ) : loading && !page ? (
          <p className="text-sm text-zinc-500 dark:text-zinc-400">Loading audit events…</p>
        ) : page?.items.length === 0 ? (
          <p className="text-sm text-zinc-500 dark:text-zinc-400">No audit events match these filters.</p>
        ) : (
          <ul className={`space-y-2 ${loading ? "opacity-60" : ""}`}>
            {page?.items.map((event) => <EventRow key={event.id} event={event} />)}
          </ul>
        )}

        {page && page.total > 0 && (
          <div className="mt-5 flex items-center justify-between gap-3">
            <p className="text-xs text-zinc-500 dark:text-zinc-400">
              Showing {first}–{last} of {page.total}
            </p>
            <div className="flex gap-2">
              <button
                type="button"
                className={`${headerBtn} disabled:opacity-40 disabled:pointer-events-none`}
                disabled={offset === 0 || loading}
                onClick={() => setOffset((current) => Math.max(0, current - PAGE_SIZE))}
              >
                Previous
              </button>
              <button
                type="button"
                className={`${headerBtn} disabled:opacity-40 disabled:pointer-events-none`}
                disabled={offset + PAGE_SIZE >= page.total || loading}
                onClick={() => setOffset((current) => current + PAGE_SIZE)}
              >
                Next
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
