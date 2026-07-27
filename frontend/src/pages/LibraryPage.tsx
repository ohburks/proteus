import { useEffect, useState } from "react";
import { api, ApiError } from "../lib/api";
import type { Rubric, RubricCriterion } from "../lib/types";
import { PageHeader, Tabs, helpClass, selectClass } from "../components/ui";

interface RubricSummary {
  rubric_id: string;
  version: string;
  genre: string;
  notes: string;
}

function CriterionRow({
  criterion,
  expanded,
  onToggle,
}: {
  criterion: RubricCriterion;
  expanded: boolean;
  onToggle: () => void;
}) {
  const scores = ["0", "1", "2", "3", "4", "5"];
  return (
    <li>
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={expanded}
        className="w-full px-4 py-3 text-left hover:bg-black/[0.03] dark:hover:bg-white/5 transition-colors"
      >
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <div className="flex items-center gap-2 flex-wrap mb-1.5">
              <span className="text-zinc-800 dark:text-zinc-200 font-medium">{criterion.criterionId}</span>
              <span className="px-2 py-0.5 text-xs font-medium rounded-full bg-zinc-500/15 text-zinc-600 dark:text-zinc-400">
                {criterion.standard}
              </span>
              <span
                className={`px-2 py-0.5 text-xs font-medium rounded-full ${
                  criterion.referenceability === "weak"
                    ? "bg-orange-500/15 text-orange-700 dark:text-orange-400"
                    : "bg-green-500/15 text-green-700 dark:text-green-400"
                }`}
              >
                {criterion.referenceability} reference
              </span>
            </div>
            <p className="text-sm text-zinc-700 dark:text-zinc-300">{criterion.statement}</p>
          </div>
          <span className="shrink-0 text-xs text-zinc-400 dark:text-zinc-500 mt-0.5">
            {expanded ? "Hide anchors ↑" : "View anchors ↓"}
          </span>
        </div>
      </button>

      {expanded && (
        <div className="border-t border-zinc-200 dark:border-white/5 bg-black/[0.015] dark:bg-white/[0.015] px-4 py-4">
          <div className="flex items-center justify-between gap-2 mb-3">
            <p className="text-xs font-medium text-zinc-500 dark:text-zinc-400">Score anchors</p>
            <p className="text-xs text-zinc-400 dark:text-zinc-500">Scale {criterion.scale}</p>
          </div>
          <div className="grid gap-2 sm:grid-cols-2">
            {scores.map((score) => (
              <div
                key={score}
                className="flex items-start gap-3 rounded-xl border border-zinc-200 dark:border-white/5 bg-white/70 dark:bg-white/[0.025] p-3"
              >
                <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-blue-500/15 text-xs font-semibold text-blue-700 dark:text-blue-400">
                  {score}
                </span>
                <p className="text-xs leading-5 text-zinc-600 dark:text-zinc-400">
                  {criterion.anchors[score] ?? "No anchor provided."}
                </p>
              </div>
            ))}
          </div>
        </div>
      )}
    </li>
  );
}

export function LibraryPage() {
  const [rubrics, setRubrics] = useState<RubricSummary[]>([]);
  const [rubricKey, setRubricKey] = useState("");
  const [rubric, setRubric] = useState<Rubric | null>(null);
  const [activeDimension, setActiveDimension] = useState("");
  const [expandedCriterion, setExpandedCriterion] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .get<RubricSummary[]>("/api/rubrics")
      .then((rs) => {
        setRubrics(rs);
        if (rs.length) setRubricKey(`${rs[0].rubric_id}::${rs[0].version}`);
      })
      .catch((err) => setError(err instanceof ApiError ? err.message : "Failed to load rubrics"));
  }, []);

  useEffect(() => {
    if (!rubricKey) return;
    const [rubric_id, version] = rubricKey.split("::");
    setRubric(null);
    setExpandedCriterion(null);
    setError(null);
    api
      .get<Rubric>(`/api/rubrics/${rubric_id}/${version}`)
      .then((nextRubric) => {
        setRubric(nextRubric);
        setActiveDimension(nextRubric.criteria[0]?.dimension ?? "");
      })
      .catch((err) => setError(err instanceof ApiError ? err.message : "Failed to load rubric"));
  }, [rubricKey]);

  const dimensionOrder = rubric ? [...new Set(rubric.criteria.map((c) => c.dimension))] : [];
  const selectedSummary = rubrics.find((item) => `${item.rubric_id}::${item.version}` === rubricKey);
  const visibleCriteria = rubric?.criteria.filter((criterion) => criterion.dimension === activeDimension) ?? [];

  return (
    <div className="min-h-[calc(100vh-3.5rem)] bg-app-light dark:bg-app-dark">
      <PageHeader
        title="Rubric library"
        subtitle={`${rubrics.length} rubric${rubrics.length === 1 ? "" : "s"} available`}
      />
      <div className="max-w-3xl mx-auto px-6 py-6">
        {rubrics.length > 0 && (
          <section className="bg-blue-500/[0.06] dark:bg-blue-500/10 border border-blue-500/20 rounded-2xl p-4 mb-6">
            <p className="text-xs font-medium text-blue-700 dark:text-blue-300 mb-2">Viewing rubric</p>
            <div className="flex flex-col sm:flex-row sm:items-center gap-3">
              <select
                aria-label="Rubric"
                className={`${selectClass} w-full sm:w-auto sm:min-w-72`}
                value={rubricKey}
                onChange={(e) => setRubricKey(e.target.value)}
              >
                {rubrics.map((item) => (
                  <option
                    key={`${item.rubric_id}::${item.version}`}
                    value={`${item.rubric_id}::${item.version}`}
                  >
                    {item.rubric_id} v{item.version}
                  </option>
                ))}
              </select>
              {rubric && (
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="px-2.5 py-0.5 text-xs font-medium rounded-full bg-blue-500/15 text-blue-700 dark:text-blue-300">
                    {rubric.genre}
                  </span>
                  <span className="text-xs text-zinc-500 dark:text-zinc-400">
                    {rubric.criteria.length} criteria · {dimensionOrder.length} dimensions
                  </span>
                </div>
              )}
            </div>
            {selectedSummary?.notes && (
              <p className={`${helpClass} mt-3 max-w-2xl`}>{selectedSummary.notes}</p>
            )}
          </section>
        )}

        {error ? (
          <p className="text-sm text-red-600 dark:text-red-400">{error}</p>
        ) : !rubric ? (
          <p className="text-zinc-500 dark:text-zinc-400">Loading…</p>
        ) : dimensionOrder.length === 0 ? (
          <p className="text-zinc-500 dark:text-zinc-400">This rubric has no criteria yet.</p>
        ) : (
          <>
            <div className="rubric-tabs-scroll -mx-1 overflow-x-auto px-1 pb-3 mb-1">
              <Tabs
                className="min-w-max"
                active={activeDimension}
                onChange={(dimension) => {
                  setActiveDimension(dimension);
                  setExpandedCriterion(null);
                }}
                tabs={dimensionOrder.map((dimension) => ({
                  key: dimension,
                  label: `${dimension} (${rubric.criteria.filter((c) => c.dimension === dimension).length})`,
                }))}
              />
            </div>

            <ul className="divide-y divide-zinc-200 dark:divide-white/5 bg-surface-light dark:bg-surface-dark border border-zinc-200 dark:border-transparent rounded-2xl overflow-hidden">
              {visibleCriteria.map((criterion) => (
                <CriterionRow
                  key={criterion.criterionId}
                  criterion={criterion}
                  expanded={expandedCriterion === criterion.criterionId}
                  onToggle={() =>
                    setExpandedCriterion((current) =>
                      current === criterion.criterionId ? null : criterion.criterionId,
                    )
                  }
                />
              ))}
            </ul>
          </>
        )}
      </div>
    </div>
  );
}
