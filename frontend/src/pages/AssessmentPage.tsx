import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../lib/api";
import type { AssessmentDetail } from "../lib/types";

export function AssessmentPage() {
  const { assessmentId } = useParams<{ assessmentId: string }>();
  const [detail, setDetail] = useState<AssessmentDetail | null>(null);

  useEffect(() => {
    if (!assessmentId) return;
    api.get<AssessmentDetail>(`/api/assessments/${assessmentId}`).then(setDetail);
  }, [assessmentId]);

  if (!detail) return <p className="p-6 text-zinc-500 dark:text-zinc-400">Loading…</p>;

  return (
    <div className="max-w-3xl mx-auto px-6 py-8 bg-app-light dark:bg-app-dark min-h-[calc(100vh-3.5rem)]">
      <h1 className="text-xl font-semibold text-zinc-900 dark:text-zinc-100 mb-1">Assessment results</h1>
      <p className="text-sm text-zinc-500 dark:text-zinc-400 mb-6">Status: {detail.status}</p>

      <ul className="divide-y divide-zinc-200 dark:divide-white/5 bg-surface-light dark:bg-surface-dark border border-zinc-200 dark:border-transparent rounded-2xl overflow-hidden">
        {/* §16.3: every criterion is always listed; a divergence badge marks
            the ones exceeding the instructor's threshold, nothing is hidden. */}
        {detail.criteria.map((c) => (
          <li key={c.criterion_id}>
            <Link
              to={`/assessments/${assessmentId}/criteria/${c.criterion_id}`}
              className="flex items-center justify-between px-4 py-3 hover:bg-black/[0.03] dark:hover:bg-white/5"
            >
              <span className="text-zinc-800 dark:text-zinc-200 font-medium">{c.criterion_id}</span>
              <span className="flex items-center gap-2">
                {c.exceeds_threshold && (
                  <span className="px-2.5 py-0.5 text-xs font-medium rounded-full bg-amber-500/15 text-amber-700 dark:text-amber-400">
                    divergent
                  </span>
                )}
                {/* High spread (a path's own multi-pass results disagreed with
                    each other) is an additive signal alongside divergence
                    (the two paths disagreeing with each other) — kept as its
                    own badge, never merged into "divergent". */}
                {c.high_spread && (
                  <span className="px-2.5 py-0.5 text-xs font-medium rounded-full bg-purple-500/15 text-purple-700 dark:text-purple-400">
                    high spread
                  </span>
                )}
                {c.output_source === "override" && (
                  <span className="px-2.5 py-0.5 text-xs font-medium rounded-full bg-blue-500/15 text-blue-700 dark:text-blue-400">
                    overridden
                  </span>
                )}
                {/* "incomplete" (grading died before this criterion's output
                    path finished) is not the same as a graded "no-evidence" —
                    its own badge and hue, distinct from the other states. */}
                {c.output_source === "incomplete" ? (
                  <span className="px-2.5 py-0.5 text-xs font-medium rounded-full bg-pink-500/15 text-pink-700 dark:text-pink-400">
                    incomplete
                  </span>
                ) : (
                  <span className="text-zinc-900 dark:text-zinc-100 font-semibold">{c.output_score ?? "no-evidence"}</span>
                )}
              </span>
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}
