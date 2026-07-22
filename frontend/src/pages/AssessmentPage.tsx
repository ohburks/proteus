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

  if (!detail) return <p className="p-6 text-gray-500 dark:text-gray-400">Loading…</p>;

  return (
    <div className="max-w-3xl mx-auto px-6 py-8 bg-gray-50 dark:bg-gray-950 min-h-[calc(100vh-3.5rem)]">
      <h1 className="text-xl font-semibold text-gray-900 dark:text-gray-100 mb-1">Assessment results</h1>
      <p className="text-sm text-gray-500 dark:text-gray-400 mb-6">Status: {detail.status}</p>

      <ul className="divide-y divide-gray-200 dark:divide-gray-800 bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-lg overflow-hidden">
        {/* §16.3: every criterion is always listed; a divergence badge marks
            the ones exceeding the instructor's threshold, nothing is hidden. */}
        {detail.criteria.map((c) => (
          <li key={c.criterion_id}>
            <Link
              to={`/assessments/${assessmentId}/criteria/${c.criterion_id}`}
              className="flex items-center justify-between px-4 py-3 hover:bg-gray-50 dark:hover:bg-gray-800"
            >
              <span className="text-gray-800 dark:text-gray-200 font-medium">{c.criterion_id}</span>
              <span className="flex items-center gap-2">
                {c.exceeds_threshold && (
                  <span className="px-2 py-0.5 text-xs rounded-full bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300">
                    divergent
                  </span>
                )}
                {/* High spread (a path's own multi-pass results disagreed with
                    each other) is an additive signal alongside divergence
                    (the two paths disagreeing with each other) — kept as its
                    own badge, never merged into "divergent". */}
                {c.high_spread && (
                  <span className="px-2 py-0.5 text-xs rounded-full bg-purple-100 text-purple-800 dark:bg-purple-900/40 dark:text-purple-300">
                    high spread
                  </span>
                )}
                {c.output_source === "override" && (
                  <span className="px-2 py-0.5 text-xs rounded-full bg-blue-100 text-blue-800 dark:bg-blue-900/40 dark:text-blue-300">
                    overridden
                  </span>
                )}
                <span className="text-gray-900 dark:text-gray-100 font-semibold">
                  {c.output_score ?? "no-evidence"}
                </span>
              </span>
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}
