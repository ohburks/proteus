import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../lib/api";
import type { AssessmentCriterionSummary, AssessmentDetail, Rubric } from "../lib/types";

function CriterionRow({ assessmentId, c }: { assessmentId: string; c: AssessmentCriterionSummary }) {
  return (
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
  );
}

export function AssessmentPage() {
  const { assessmentId } = useParams<{ assessmentId: string }>();
  const [detail, setDetail] = useState<AssessmentDetail | null>(null);
  const [rubric, setRubric] = useState<Rubric | null>(null);

  useEffect(() => {
    if (!assessmentId) return;
    api.get<AssessmentDetail>(`/api/assessments/${assessmentId}`).then(setDetail);
  }, [assessmentId]);

  useEffect(() => {
    if (!detail) return;
    api.get<Rubric>(`/api/rubrics/${detail.rubric_id}/${detail.rubric_version}`).then(setRubric);
  }, [detail]);

  if (!detail) return <p className="p-6 text-zinc-500 dark:text-zinc-400">Loading…</p>;

  // §16.3: every criterion is always listed; a divergence badge marks the
  // ones exceeding the instructor's threshold, nothing is hidden. Group by
  // dimension (e.g. "Claims (W1a)") once the rubric has loaded, in the
  // rubric's own criteria order — falls back to a flat list until then.
  const dimensionOrder = rubric ? [...new Set(rubric.criteria.map((rc) => rc.dimension))] : [];
  const dimensionOf = (cid: string) => rubric?.criteria.find((rc) => rc.criterionId === cid)?.dimension;

  return (
    <div className="max-w-3xl mx-auto px-6 py-8 bg-app-light dark:bg-app-dark min-h-[calc(100vh-3.5rem)]">
      <h1 className="text-xl font-semibold text-zinc-900 dark:text-zinc-100 mb-1">Assessment results</h1>
      <p className="text-sm text-zinc-500 dark:text-zinc-400 mb-6">Status: {detail.status}</p>

      {!rubric ? (
        <ul className="divide-y divide-zinc-200 dark:divide-white/5 bg-surface-light dark:bg-surface-dark border border-zinc-200 dark:border-transparent rounded-2xl overflow-hidden">
          {detail.criteria.map((c) => (
            <CriterionRow key={c.criterion_id} assessmentId={assessmentId!} c={c} />
          ))}
        </ul>
      ) : (
        [...dimensionOrder, "Other"].map((dimension) => {
          const rows = detail.criteria.filter((c) =>
            dimension === "Other" ? dimensionOf(c.criterion_id) === undefined : dimensionOf(c.criterion_id) === dimension,
          );
          if (rows.length === 0) return null;
          return (
            <div key={dimension} className="mb-4">
              <h2 className="text-sm font-semibold text-zinc-500 dark:text-zinc-400 mb-2">{dimension}</h2>
              <ul className="divide-y divide-zinc-200 dark:divide-white/5 bg-surface-light dark:bg-surface-dark border border-zinc-200 dark:border-transparent rounded-2xl overflow-hidden">
                {rows.map((c) => (
                  <CriterionRow key={c.criterion_id} assessmentId={assessmentId!} c={c} />
                ))}
              </ul>
            </div>
          );
        })
      )}
    </div>
  );
}
