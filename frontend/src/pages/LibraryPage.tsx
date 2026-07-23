import { useEffect, useState } from "react";
import { api } from "../lib/api";
import type { Rubric, RubricCriterion } from "../lib/types";

interface RubricSummary {
  rubric_id: string;
  version: string;
  genre: string;
  notes: string;
}

function CriterionCard({ c }: { c: RubricCriterion }) {
  const scores = ["0", "1", "2", "3", "4", "5"];
  return (
    <li className="px-4 py-3">
      <div className="flex items-center justify-between mb-1">
        <span className="text-zinc-800 dark:text-zinc-200 font-medium">{c.criterionId}</span>
        <span className="text-xs text-zinc-400 dark:text-zinc-500">{c.standard} · scale {c.scale}</span>
      </div>
      <p className="text-sm text-zinc-700 dark:text-zinc-300 mb-2">{c.statement}</p>
      <div className="space-y-1">
        {scores.map((s) => (
          <p key={s} className="text-xs text-zinc-600 dark:text-zinc-400">
            <span className="font-semibold text-zinc-500 dark:text-zinc-400">{s}:</span>{" "}
            <span className="italic">{c.anchors[s] ?? "—"}</span>
          </p>
        ))}
      </div>
    </li>
  );
}

export function LibraryPage() {
  const [rubrics, setRubrics] = useState<RubricSummary[]>([]);
  const [rubricKey, setRubricKey] = useState("");
  const [rubric, setRubric] = useState<Rubric | null>(null);

  useEffect(() => {
    api.get<RubricSummary[]>("/api/rubrics").then((rs) => {
      setRubrics(rs);
      if (rs.length) setRubricKey(`${rs[0].rubric_id}::${rs[0].version}`);
    });
  }, []);

  useEffect(() => {
    if (!rubricKey) return;
    const [rubric_id, version] = rubricKey.split("::");
    api.get<Rubric>(`/api/rubrics/${rubric_id}/${version}`).then(setRubric);
  }, [rubricKey]);

  const dimensionOrder = rubric ? [...new Set(rubric.criteria.map((c) => c.dimension))] : [];

  return (
    <div className="max-w-3xl mx-auto px-6 py-8 bg-app-light dark:bg-app-dark min-h-[calc(100vh-3.5rem)]">
      <h1 className="text-xl font-semibold text-zinc-900 dark:text-zinc-100 mb-6">Library</h1>

      <select
        className="w-full px-3 py-2 mb-6 border border-zinc-300 dark:border-white/10 rounded-lg bg-white dark:bg-white/5 text-zinc-900 dark:text-zinc-100"
        value={rubricKey}
        onChange={(e) => setRubricKey(e.target.value)}
      >
        {rubrics.map((r) => (
          <option key={`${r.rubric_id}::${r.version}`} value={`${r.rubric_id}::${r.version}`}>
            {r.rubric_id} v{r.version}
          </option>
        ))}
      </select>

      {!rubric ? (
        <p className="text-zinc-500 dark:text-zinc-400">Loading…</p>
      ) : (
        <>
          <p className="text-sm text-zinc-500 dark:text-zinc-400 mb-6">
            {rubric.genre}
            {rubric.notes && <> — {rubric.notes}</>}
          </p>
          {dimensionOrder.map((dimension) => (
            <div key={dimension} className="mb-4">
              <h2 className="text-sm font-semibold text-zinc-500 dark:text-zinc-400 mb-2">{dimension}</h2>
              <ul className="divide-y divide-zinc-200 dark:divide-white/5 bg-surface-light dark:bg-surface-dark border border-zinc-200 dark:border-transparent rounded-2xl overflow-hidden">
                {rubric.criteria
                  .filter((c) => c.dimension === dimension)
                  .map((c) => (
                    <CriterionCard key={c.criterionId} c={c} />
                  ))}
              </ul>
            </div>
          ))}
        </>
      )}
    </div>
  );
}
