import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../lib/api";
import type { StudentHistory, StudentHistoryEntry } from "../lib/types";

function StatusBadge({ status }: { status: StudentHistoryEntry["status"] }) {
  if (status === null) {
    return (
      <span className="px-2 py-0.5 text-xs font-medium rounded-full bg-zinc-500/15 text-zinc-600 dark:text-zinc-400">
        ungraded
      </span>
    );
  }
  if (status === "running" || status === "pending") {
    return (
      <span className="px-2.5 py-0.5 text-xs font-medium rounded-full bg-blue-500/15 text-blue-700 dark:text-blue-400">
        grading…
      </span>
    );
  }
  if (status === "failed") {
    return (
      <span className="px-2.5 py-0.5 text-xs font-medium rounded-full bg-pink-500/15 text-pink-700 dark:text-pink-400">
        failed
      </span>
    );
  }
  if (status === "cancelled") {
    return (
      <span className="px-2.5 py-0.5 text-xs font-medium rounded-full bg-zinc-500/15 text-zinc-600 dark:text-zinc-400">
        cancelled
      </span>
    );
  }
  return (
    <span className="px-2.5 py-0.5 text-xs font-medium rounded-full bg-green-500/15 text-green-700 dark:text-green-400">
      graded
    </span>
  );
}

export function StudentHistoryPage() {
  const { studentId } = useParams<{ studentId: string }>();
  const [data, setData] = useState<StudentHistory | null>(null);

  useEffect(() => {
    if (!studentId) return;
    api.get<StudentHistory>(`/api/students/${studentId}/history`).then(setData);
  }, [studentId]);

  if (!data) return <p className="p-6 text-zinc-500 dark:text-zinc-400">Loading…</p>;

  const { student, history } = data;

  return (
    <div className="max-w-3xl mx-auto px-6 py-8 bg-app-light dark:bg-app-dark min-h-[calc(100vh-3.5rem)]">
      <div className="flex items-center gap-2 mb-1">
        <h1 className="text-xl font-semibold text-zinc-900 dark:text-zinc-100">{student.display_name}</h1>
        {student.status === "archived" && (
          <span className="px-2 py-0.5 text-xs font-medium rounded-full bg-zinc-500/15 text-zinc-600 dark:text-zinc-400">
            archived
          </span>
        )}
      </div>
      <p className="text-sm text-zinc-500 dark:text-zinc-400 mb-6">
        {student.external_ref ? `Ref: ${student.external_ref}` : "No external ref"}
      </p>

      {history.length === 0 ? (
        <p className="text-zinc-500 dark:text-zinc-400">No essays yet for this student.</p>
      ) : (
        <ul className="space-y-2">
          {history.map((h) => (
            <li
              key={h.essay_id}
              className="bg-surface-light dark:bg-surface-dark border border-zinc-200 dark:border-transparent rounded-2xl p-4"
            >
              <div className="flex items-center justify-between mb-1">
                <span className="text-zinc-800 dark:text-zinc-200 font-medium">{h.assignment_name}</span>
                <span className="text-xs text-zinc-400 dark:text-zinc-500">
                  {new Date(h.created_at).toLocaleDateString()}
                </span>
              </div>
              <div className="flex items-center gap-2 flex-wrap mb-2">
                <StatusBadge status={h.status} />
                {h.avg_score !== null && (
                  <span className="text-zinc-900 dark:text-zinc-100 font-semibold text-sm">
                    avg {h.avg_score.toFixed(1)}{" "}
                    <span className="text-xs text-zinc-500 dark:text-zinc-400 font-normal">
                      (n={h.n_criteria})
                    </span>
                  </span>
                )}
                {h.n_divergent > 0 && (
                  <span className="px-2.5 py-0.5 text-xs font-medium rounded-full bg-amber-500/15 text-amber-700 dark:text-amber-400">
                    {h.n_divergent} divergent
                  </span>
                )}
                {h.n_high_spread > 0 && (
                  <span className="px-2.5 py-0.5 text-xs font-medium rounded-full bg-purple-500/15 text-purple-700 dark:text-purple-400">
                    {h.n_high_spread} high spread
                  </span>
                )}
                {h.needs_review && (
                  <span className="px-2.5 py-0.5 text-xs font-medium rounded-full bg-red-500/15 text-red-700 dark:text-red-400">
                    needs review
                  </span>
                )}
              </div>
              {h.assessment_id && (
                <Link
                  to={`/assessments/${h.assessment_id}`}
                  className="text-xs text-blue-600 dark:text-blue-400 hover:underline"
                >
                  View assessment →
                </Link>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
