import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../lib/api";
import type { Assignment, AssignmentBreakdown, Rubric } from "../lib/types";

export function AssignmentBreakdownPage() {
  const { assignmentId } = useParams<{ assignmentId: string }>();
  const [assignment, setAssignment] = useState<Assignment | null>(null);
  const [rubric, setRubric] = useState<Rubric | null>(null);
  const [breakdown, setBreakdown] = useState<AssignmentBreakdown | null>(null);

  useEffect(() => {
    if (!assignmentId) return;
    api.get<Assignment>(`/api/assignments/${assignmentId}`).then(setAssignment);
    api.get<AssignmentBreakdown>(`/api/assignments/${assignmentId}/breakdown`).then(setBreakdown);
  }, [assignmentId]);

  useEffect(() => {
    if (!assignment) return;
    api.get<Rubric>(`/api/rubrics/${assignment.rubric_id}/${assignment.rubric_version}`).then(setRubric);
  }, [assignment]);

  if (!breakdown || !rubric) return <p className="p-6 text-zinc-500 dark:text-zinc-400">Loading…</p>;

  const byCriterion = new Map(breakdown.criteria.map((c) => [c.criterion_id, c]));
  const dimensionOrder = [...new Set(rubric.criteria.map((rc) => rc.dimension))];

  return (
    <div className="max-w-3xl mx-auto px-6 py-8 bg-app-light dark:bg-app-dark min-h-[calc(100vh-3.5rem)]">
      <Link to={`/assignments/${assignmentId}`} className="text-sm text-blue-600 dark:text-blue-400 hover:underline">
        ← Back to essays
      </Link>
      <h1 className="text-xl font-semibold text-zinc-900 dark:text-zinc-100 mt-2 mb-1">Class breakdown</h1>
      <p className="text-sm text-zinc-500 dark:text-zinc-400 mb-6">
        {breakdown.n_graded_essays} of {breakdown.n_essays} essays graded
      </p>

      {dimensionOrder.map((dimension) => (
        <div key={dimension} className="mb-4">
          <h2 className="text-sm font-semibold text-zinc-500 dark:text-zinc-400 mb-2">{dimension}</h2>
          <ul className="divide-y divide-zinc-200 dark:divide-white/5 bg-surface-light dark:bg-surface-dark border border-zinc-200 dark:border-transparent rounded-2xl overflow-hidden">
            {rubric.criteria
              .filter((rc) => rc.dimension === dimension)
              .map((rc) => {
                const stats = byCriterion.get(rc.criterionId);
                return (
                  <li key={rc.criterionId} className="px-4 py-3">
                    <div className="flex items-center justify-between mb-1">
                      <span className="text-zinc-800 dark:text-zinc-200 font-medium">{rc.criterionId}</span>
                      {stats ? (
                        <span className="text-zinc-900 dark:text-zinc-100 font-semibold">
                          avg {stats.avg_score.toFixed(1)}{" "}
                          <span className="text-xs text-zinc-500 dark:text-zinc-400 font-normal">
                            ({stats.min_score}–{stats.max_score} range, n={stats.n_graded})
                          </span>
                        </span>
                      ) : (
                        <span className="text-zinc-400 dark:text-zinc-500 text-sm">no data yet</span>
                      )}
                    </div>
                    {stats && (stats.n_divergent > 0 || stats.n_high_spread > 0) && (
                      <div className="flex gap-2">
                        {stats.n_divergent > 0 && (
                          <span className="px-2.5 py-0.5 text-xs font-medium rounded-full bg-amber-500/15 text-amber-700 dark:text-amber-400">
                            {stats.n_divergent} divergent
                          </span>
                        )}
                        {stats.n_high_spread > 0 && (
                          <span className="px-2.5 py-0.5 text-xs font-medium rounded-full bg-purple-500/15 text-purple-700 dark:text-purple-400">
                            {stats.n_high_spread} high spread
                          </span>
                        )}
                      </div>
                    )}
                  </li>
                );
              })}
          </ul>
        </div>
      ))}
    </div>
  );
}
