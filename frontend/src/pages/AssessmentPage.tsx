import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, ApiError, downloadFile } from "../lib/api";
import type {
  AssessmentCriterionSummary,
  AssessmentDetail,
  RelevanceCheck,
  Rubric,
} from "../lib/types";
import { PageHeader, headerBtn } from "../components/ui";

const submissionTypeLabels: Record<RelevanceCheck["submission_type"], string> = {
  student_response: "Student response",
  instructions: "Instructions",
  rubric: "Rubric",
  source_material: "Source material",
  other: "Other",
};

function RelevanceCheckCard({ check }: { check: RelevanceCheck | null }) {
  const badge =
    check?.decision === "grade"
      ? {
          label: "passed",
          className: "bg-green-500/15 text-green-700 dark:text-green-400",
        }
      : check?.decision === "reject"
        ? {
            label: "rejected",
            className: "bg-red-500/15 text-red-700 dark:text-red-400",
          }
        : check?.decision === "manual_review"
          ? {
              label: "manual review",
              className: "bg-amber-500/15 text-amber-700 dark:text-amber-400",
            }
          : {
              label: "not available",
              className: "bg-zinc-500/15 text-zinc-600 dark:text-zinc-400",
            };

  return (
    <section className="mb-6 overflow-hidden rounded-2xl border border-zinc-200 bg-surface-light dark:border-transparent dark:bg-surface-dark">
      <div className="flex items-center justify-between gap-3 border-b border-zinc-200 px-4 py-3 dark:border-white/5">
        <h2 className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">Relevance check</h2>
        <span className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${badge.className}`}>
          {badge.label}
        </span>
      </div>
      <div className="space-y-4 px-4 py-4">
        {check ? (
          <>
            <p className="text-sm leading-6 text-zinc-700 dark:text-zinc-300">{check.rationale}</p>
            <dl className="flex flex-wrap gap-2 text-xs">
              <div className="rounded-lg bg-black/[0.035] px-2.5 py-1.5 dark:bg-white/5">
                <dt className="inline text-zinc-500 dark:text-zinc-400">Detected: </dt>
                <dd className="inline font-medium text-zinc-800 dark:text-zinc-200">
                  {submissionTypeLabels[check.submission_type]}
                </dd>
              </div>
              <div className="rounded-lg bg-black/[0.035] px-2.5 py-1.5 dark:bg-white/5">
                <dt className="inline text-zinc-500 dark:text-zinc-400">Responds to prompt: </dt>
                <dd className="inline font-medium text-zinc-800 dark:text-zinc-200">
                  {check.responds_to_prompt ? "Yes" : "No"}
                </dd>
              </div>
              <div className="rounded-lg bg-black/[0.035] px-2.5 py-1.5 dark:bg-white/5">
                <dt className="inline text-zinc-500 dark:text-zinc-400">Enough content: </dt>
                <dd className="inline font-medium text-zinc-800 dark:text-zinc-200">
                  {check.has_sufficient_content ? "Yes" : "No"}
                </dd>
              </div>
            </dl>
            {check.evidence.length > 0 && (
              <div>
                <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
                  Supporting evidence
                </h3>
                <ul className="space-y-2">
                  {check.evidence.map((item, index) => (
                    <li
                      key={`${item.quote}-${index}`}
                      className="rounded-xl border border-zinc-200 px-3 py-2.5 dark:border-white/10"
                    >
                      <blockquote className="text-sm text-zinc-800 dark:text-zinc-200">
                        “{item.quote}”
                      </blockquote>
                      <p className="mt-1 text-xs text-zinc-500 dark:text-zinc-400">{item.reasoning}</p>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </>
        ) : (
          <p className="text-sm text-zinc-500 dark:text-zinc-400">
            This assessment was created before relevance checking was enabled.
          </p>
        )}
      </div>
    </section>
  );
}

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
          {c.review_reasons.includes("weak_referenceability") && (
            <span className="px-2.5 py-0.5 text-xs font-medium rounded-full bg-orange-500/15 text-orange-700 dark:text-orange-400">
              weak criterion
            </span>
          )}
          {c.review_reasons.includes("unsupported_evidence") && (
            <span className="px-2.5 py-0.5 text-xs font-medium rounded-full bg-red-500/15 text-red-700 dark:text-red-400">
              unsupported evidence
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
  const [pdfError, setPdfError] = useState<string | null>(null);

  async function downloadPdf() {
    setPdfError(null);
    try {
      await downloadFile(`/api/assessments/${assessmentId}/report.pdf`, "grade_report.pdf");
    } catch (err) {
      setPdfError(err instanceof ApiError ? err.message : "Failed to download PDF");
    }
  }
  const dimensionByCriterion = useMemo(
    () => new Map(rubric?.criteria.map((criterion) => [criterion.criterionId, criterion.dimension]) ?? []),
    [rubric],
  );

  useEffect(() => {
    if (!assessmentId) return;
    api.get<AssessmentDetail>(`/api/assessments/${assessmentId}`).then(setDetail);
  }, [assessmentId]);

  useEffect(() => {
    if (!detail) return;
    api.get<Rubric>(`/api/rubrics/${detail.rubric_id}/${detail.rubric_version}`).then(setRubric);
  }, [detail]);

  if (!detail) {
    return (
      <div className="min-h-[calc(100vh-3.5rem)] bg-app-light dark:bg-app-dark">
        <PageHeader title="Assessment results" />
        <p className="max-w-3xl mx-auto px-6 py-8 text-sm text-zinc-500 dark:text-zinc-400">Loading…</p>
      </div>
    );
  }

  // §16.3: every criterion is always listed; a divergence badge marks the
  // ones exceeding the instructor's threshold, nothing is hidden. Group by
  // dimension (e.g. "Claims (W1a)") once the rubric has loaded, in the
  // rubric's own criteria order — falls back to a flat list until then.
  const dimensionOrder = rubric ? [...new Set(rubric.criteria.map((rc) => rc.dimension))] : [];
  const dimensionOf = (cid: string) => dimensionByCriterion.get(cid);

  return (
    <div className="min-h-[calc(100vh-3.5rem)] bg-app-light dark:bg-app-dark">
      <PageHeader
        title="Assessment results"
        backTo={`/assignments/${detail.assignment_id}`}
        backLabel="Back to assignment"
        subtitle={`Status: ${detail.status}`}
        right={
          <button onClick={downloadPdf} className={headerBtn}>
            Download PDF
          </button>
        }
      />
      <div className="max-w-3xl mx-auto px-6 py-6">
        {pdfError && <p className="mb-4 text-sm text-red-600 dark:text-red-400">{pdfError}</p>}
        <RelevanceCheckCard check={detail.relevance_check} />
        {detail.status === "complete" &&
        detail.relevance_check &&
        detail.relevance_check.decision !== "grade" &&
        detail.criteria.length === 0 ? (
          <div className="rounded-2xl border border-zinc-200 bg-surface-light px-4 py-5 text-sm text-zinc-600 dark:border-transparent dark:bg-surface-dark dark:text-zinc-400">
            This earlier assessment has no rubric grades. Regrade the submission to apply the new
            advisory relevance behavior.
          </div>
        ) : !rubric ? (
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
    </div>
  );
}
