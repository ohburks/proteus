import { useEffect, useState } from "react";
import { api } from "../lib/api";
import type { Rubric } from "../lib/types";

interface RubricSummary {
  rubric_id: string;
  version: string;
}

export function SettingsPage() {
  const [rubrics, setRubrics] = useState<RubricSummary[]>([]);
  const [rubricKey, setRubricKey] = useState("");
  const [rubric, setRubric] = useState<Rubric | null>(null);
  const [criterionId, setCriterionId] = useState("");
  const [divergenceThreshold, setDivergenceThreshold] = useState(2);
  const [poolSize, setPoolSize] = useState(5);
  const [gradingPhilosophy, setGradingPhilosophy] = useState("");
  const [rationaleTone, setRationaleTone] = useState("");
  const [saved, setSaved] = useState<string | null>(null);

  useEffect(() => {
    api.get<RubricSummary[]>("/api/rubrics").then((rs) => {
      setRubrics(rs);
      if (rs.length) setRubricKey(`${rs[0].rubric_id}::${rs[0].version}`);
    });
  }, []);

  useEffect(() => {
    if (!rubricKey) return;
    const [rubric_id, version] = rubricKey.split("::");
    api.get<Rubric>(`/api/rubrics/${rubric_id}/${version}`).then((r) => {
      setRubric(r);
      if (r.criteria.length) setCriterionId(r.criteria[0].criterionId);
    });
  }, [rubricKey]);

  async function saveThresholds(e: React.FormEvent) {
    e.preventDefault();
    if (!rubric || !criterionId) return;
    await api.put("/api/settings/divergence-threshold", {
      rubric_id: rubric.rubricId,
      criterion_id: criterionId,
      threshold: divergenceThreshold,
    });
    await api.put("/api/settings/pool-threshold", {
      rubric_id: rubric.rubricId,
      criterion_id: criterionId,
      min_scoped_pool_size: poolSize,
    });
    setSaved("Thresholds saved.");
    setTimeout(() => setSaved(null), 2000);
  }

  async function saveProfile(e: React.FormEvent) {
    e.preventDefault();
    await api.put("/api/settings/instructor-profile", {
      grading_philosophy: gradingPhilosophy || null,
      rationale_tone: rationaleTone || null,
    });
    setSaved("Instructor profile saved.");
    setTimeout(() => setSaved(null), 2000);
  }

  return (
    <div className="max-w-2xl mx-auto px-6 py-8 bg-gray-50 dark:bg-gray-950 min-h-[calc(100vh-3.5rem)]">
      <h1 className="text-xl font-semibold text-gray-900 dark:text-gray-100 mb-6">Settings</h1>
      {saved && <p className="text-sm text-emerald-600 dark:text-emerald-400 mb-3">{saved}</p>}

      <section className="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-lg p-4 mb-6">
        <h2 className="text-sm font-semibold text-gray-900 dark:text-gray-100 mb-3">
          Per-criterion thresholds (sticky until changed)
        </h2>
        <form onSubmit={saveThresholds} className="space-y-3">
          <select
            className="w-full px-3 py-2 border border-gray-300 dark:border-gray-700 rounded bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100"
            value={rubricKey}
            onChange={(e) => setRubricKey(e.target.value)}
          >
            {rubrics.map((r) => (
              <option key={`${r.rubric_id}::${r.version}`} value={`${r.rubric_id}::${r.version}`}>
                {r.rubric_id} v{r.version}
              </option>
            ))}
          </select>
          <select
            className="w-full px-3 py-2 border border-gray-300 dark:border-gray-700 rounded bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100"
            value={criterionId}
            onChange={(e) => setCriterionId(e.target.value)}
          >
            {rubric?.criteria.map((c) => (
              <option key={c.criterionId} value={c.criterionId}>
                {c.criterionId} — {c.dimension}
              </option>
            ))}
          </select>
          <div className="flex gap-4">
            <label className="flex items-center gap-2 text-sm text-gray-700 dark:text-gray-300">
              Divergence threshold
              <input
                type="number"
                min={0}
                max={5}
                value={divergenceThreshold}
                onChange={(e) => setDivergenceThreshold(Number(e.target.value))}
                className="w-16 px-2 py-1 border border-gray-300 dark:border-gray-700 rounded bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100"
              />
            </label>
            <label className="flex items-center gap-2 text-sm text-gray-700 dark:text-gray-300">
              Pool size ("enough")
              <input
                type="number"
                min={1}
                value={poolSize}
                onChange={(e) => setPoolSize(Number(e.target.value))}
                className="w-16 px-2 py-1 border border-gray-300 dark:border-gray-700 rounded bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100"
              />
            </label>
          </div>
          <button className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 dark:bg-indigo-500 dark:hover:bg-indigo-400 text-white rounded text-sm font-medium">
            Save
          </button>
        </form>
      </section>

      <section className="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-lg p-4">
        <h2 className="text-sm font-semibold text-gray-900 dark:text-gray-100 mb-3">
          Instructor profile (personalized path only)
        </h2>
        <form onSubmit={saveProfile} className="space-y-3">
          <textarea
            className="w-full px-3 py-2 border border-gray-300 dark:border-gray-700 rounded bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100"
            placeholder="Grading philosophy"
            value={gradingPhilosophy}
            onChange={(e) => setGradingPhilosophy(e.target.value)}
          />
          <select
            className="w-full px-3 py-2 border border-gray-300 dark:border-gray-700 rounded bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100"
            value={rationaleTone}
            onChange={(e) => setRationaleTone(e.target.value)}
          >
            <option value="">(unset)</option>
            <option value="terse">terse</option>
            <option value="detailed">detailed</option>
            <option value="encouraging">encouraging</option>
            <option value="blunt">blunt</option>
          </select>
          <button className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 dark:bg-indigo-500 dark:hover:bg-indigo-400 text-white rounded text-sm font-medium">
            Save
          </button>
        </form>
      </section>
    </div>
  );
}
