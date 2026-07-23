import { useEffect, useState } from "react";
import { api, ApiError } from "../lib/api";
import type { PersonalizedExcerpt, Rubric } from "../lib/types";

interface RubricSummary {
  rubric_id: string;
  version: string;
}

interface OverrideRateEntry {
  rubric_id: string;
  rubric_version: string;
  criterion_id: string;
  dimension: string | null;
  statement: string | null;
  n_graded: number;
  n_overrides: number;
  override_rate: number;
  avg_score_diff: number | null;
}

export function SettingsPage() {
  const [rubrics, setRubrics] = useState<RubricSummary[]>([]);
  const [rubricKey, setRubricKey] = useState("");
  const [rubric, setRubric] = useState<Rubric | null>(null);
  const [criterionId, setCriterionId] = useState("");
  const [divergenceThreshold, setDivergenceThreshold] = useState(2);
  const [spreadThreshold, setSpreadThreshold] = useState(1);
  const [poolSize, setPoolSize] = useState(5);
  const [gradingPhilosophy, setGradingPhilosophy] = useState("");
  const [rationaleTone, setRationaleTone] = useState("");
  const [defaultProvider, setDefaultProvider] = useState("");
  const [defaultModel, setDefaultModel] = useState("");
  // Not editable here, but must round-trip through the save: the PUT upserts
  // every profile column, so omitting this would wipe the stored value.
  const [deprioritizedCriteria, setDeprioritizedCriteria] = useState<string[] | null>(null);
  const [saved, setSaved] = useState<string | null>(null);
  const [excerpts, setExcerpts] = useState<PersonalizedExcerpt[]>([]);
  const [excerptText, setExcerptText] = useState("");
  const [sourceEssayText, setSourceEssayText] = useState("");
  const [score, setScore] = useState(0);
  const [anchorMatched, setAnchorMatched] = useState(0);
  const [rationale, setRationale] = useState("");
  const [excerptError, setExcerptError] = useState<string | null>(null);
  const [overrideRates, setOverrideRates] = useState<OverrideRateEntry[]>([]);

  useEffect(() => {
    api.get<{ criteria: OverrideRateEntry[] }>("/api/settings/override-rate").then((r) => {
      setOverrideRates(r.criteria.filter((c) => c.n_graded > 0));
    });
  }, []);

  useEffect(() => {
    api.get<RubricSummary[]>("/api/rubrics").then((rs) => {
      setRubrics(rs);
      if (rs.length) setRubricKey(`${rs[0].rubric_id}::${rs[0].version}`);
    });
    // Load the stored profile so saving edits it instead of overwriting it
    // with an empty form.
    api
      .get<{
        grading_philosophy: string | null;
        deprioritized_criteria: string[] | null;
        rationale_tone: string | null;
        default_llm_provider: string | null;
        default_llm_model: string | null;
      }>("/api/settings/instructor-profile")
      .then((p) => {
        setGradingPhilosophy(p.grading_philosophy ?? "");
        setRationaleTone(p.rationale_tone ?? "");
        setDeprioritizedCriteria(p.deprioritized_criteria);
        setDefaultProvider(p.default_llm_provider ?? "");
        setDefaultModel(p.default_llm_model ?? "");
      });
  }, []);

  // Show the thresholds actually in force for the selected criterion, not
  // hardcoded defaults.
  useEffect(() => {
    if (!rubricKey || !criterionId) return;
    const [rubric_id] = rubricKey.split("::");
    api
      .get<{ divergence_threshold: number; spread_threshold: number; min_scoped_pool_size: number }>(
        `/api/settings/thresholds?rubric_id=${rubric_id}&criterion_id=${criterionId}`,
      )
      .then((t) => {
        setDivergenceThreshold(t.divergence_threshold);
        setSpreadThreshold(t.spread_threshold);
        setPoolSize(t.min_scoped_pool_size);
      });
  }, [rubricKey, criterionId]);

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
    await api.put("/api/settings/spread-threshold", {
      rubric_id: rubric.rubricId,
      criterion_id: criterionId,
      threshold: spreadThreshold,
    });
    await api.put("/api/settings/pool-threshold", {
      rubric_id: rubric.rubricId,
      criterion_id: criterionId,
      min_scoped_pool_size: poolSize,
    });
    setSaved("Thresholds saved.");
    setTimeout(() => setSaved(null), 2000);
  }

  function refreshExcerpts() {
    if (!rubricKey || !criterionId) return;
    const [rubric_id] = rubricKey.split("::");
    api
      .get<PersonalizedExcerpt[]>(`/api/personalized-excerpts?rubric_id=${rubric_id}&criterion_id=${criterionId}`)
      .then(setExcerpts);
  }
  useEffect(refreshExcerpts, [rubricKey, criterionId]);

  async function addExcerpt(e: React.FormEvent) {
    e.preventDefault();
    setExcerptError(null);
    if (!rubricKey || !criterionId) return;
    if (!excerptText.trim() || !sourceEssayText.trim() || !rationale.trim()) {
      setExcerptError("Excerpt text, source essay text, and rationale are all required.");
      return;
    }
    const [rubric_id] = rubricKey.split("::");
    try {
      await api.post("/api/personalized-excerpts", {
        rubric_id, criterion_id: criterionId,
        excerpt_text: excerptText, score, anchor_matched: anchorMatched,
        rationale, source_essay_text: sourceEssayText,
      });
      setExcerptText("");
      setSourceEssayText("");
      setRationale("");
      setScore(0);
      setAnchorMatched(0);
      refreshExcerpts();
    } catch (err) {
      setExcerptError(err instanceof ApiError ? err.message : "Failed to add excerpt");
    }
  }

  async function deleteExcerpt(id: string) {
    if (!confirm("Delete this excerpt? It will no longer be used as grading precedent.")) return;
    try {
      await api.del(`/api/personalized-excerpts/${id}`);
      refreshExcerpts();
    } catch (err) {
      setExcerptError(err instanceof ApiError ? err.message : "Failed to delete excerpt");
    }
  }

  async function saveProfile(e: React.FormEvent) {
    e.preventDefault();
    await api.put("/api/settings/instructor-profile", {
      grading_philosophy: gradingPhilosophy || null,
      rationale_tone: rationaleTone || null,
      deprioritized_criteria: deprioritizedCriteria,
      default_llm_provider: defaultProvider || null,
      default_llm_model: defaultModel || null,
    });
    setSaved("Instructor profile saved.");
    setTimeout(() => setSaved(null), 2000);
  }

  return (
    <div className="max-w-2xl mx-auto px-6 py-8 bg-app-light dark:bg-app-dark min-h-[calc(100vh-3.5rem)]">
      <h1 className="text-xl font-semibold text-zinc-900 dark:text-zinc-100 mb-6">Settings</h1>
      {saved && <p className="text-sm text-green-600 dark:text-green-400 mb-3">{saved}</p>}

      <section className="bg-surface-light dark:bg-surface-dark border border-zinc-200 dark:border-transparent rounded-2xl p-5 mb-6">
        <h2 className="text-sm font-semibold text-blue-600 dark:text-blue-400 mb-1">Default LLM provider</h2>
        <p className="text-xs text-zinc-500 dark:text-zinc-400 mb-3">
          Pre-fills the grading page's provider/model fields. The API key is never stored here — it's still
          typed in per session on the grading page (or comes from the server default).
        </p>
        <form onSubmit={saveProfile} className="flex gap-2">
          <select
            className="px-2 py-1 border border-zinc-300 dark:border-white/10 rounded-lg bg-white dark:bg-white/5 text-zinc-900 dark:text-zinc-100 text-sm"
            value={defaultProvider}
            onChange={(e) => setDefaultProvider(e.target.value)}
          >
            <option value="">server default</option>
            <option value="openai">openai</option>
            <option value="anthropic">anthropic</option>
            <option value="gemini">gemini</option>
            <option value="groq">groq</option>
            <option value="mistral">mistral</option>
            <option value="github">github</option>
            <option value="ollama">ollama</option>
            <option value="tamu">tamu</option>
          </select>
          <input
            className="flex-1 px-2 py-1 border border-zinc-300 dark:border-white/10 rounded-lg bg-white dark:bg-white/5 text-zinc-900 dark:text-zinc-100 text-sm"
            placeholder="model (optional)"
            value={defaultModel}
            onChange={(e) => setDefaultModel(e.target.value)}
          />
          <button className="px-4 py-1 bg-blue-600 hover:bg-blue-500 dark:bg-blue-500 dark:hover:bg-blue-400 text-white rounded-lg text-sm font-medium">
            Save
          </button>
        </form>
      </section>

      <section className="bg-surface-light dark:bg-surface-dark border border-zinc-200 dark:border-transparent rounded-2xl p-5 mb-6">
        <h2 className="text-sm font-semibold text-blue-600 dark:text-blue-400 mb-3">
          Per-criterion thresholds (sticky until changed)
        </h2>
        <form onSubmit={saveThresholds} className="space-y-3">
          <select
            className="w-full px-3 py-2 border border-zinc-300 dark:border-white/10 rounded-lg bg-white dark:bg-white/5 text-zinc-900 dark:text-zinc-100"
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
            className="w-full px-3 py-2 border border-zinc-300 dark:border-white/10 rounded-lg bg-white dark:bg-white/5 text-zinc-900 dark:text-zinc-100"
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
            <label className="flex items-center gap-2 text-sm text-zinc-700 dark:text-zinc-300">
              Divergence threshold
              <input
                type="number"
                min={0}
                max={5}
                value={divergenceThreshold}
                onChange={(e) => setDivergenceThreshold(Number(e.target.value))}
                className="w-16 px-2 py-1 border border-zinc-300 dark:border-white/10 rounded-lg bg-white dark:bg-white/5 text-zinc-900 dark:text-zinc-100"
              />
            </label>
            <label className="flex items-center gap-2 text-sm text-zinc-700 dark:text-zinc-300">
              Spread threshold
              <input
                type="number"
                min={0}
                max={5}
                step={0.1}
                value={spreadThreshold}
                onChange={(e) => setSpreadThreshold(Number(e.target.value))}
                className="w-16 px-2 py-1 border border-zinc-300 dark:border-white/10 rounded-lg bg-white dark:bg-white/5 text-zinc-900 dark:text-zinc-100"
              />
            </label>
            <label className="flex items-center gap-2 text-sm text-zinc-700 dark:text-zinc-300">
              Pool size ("enough")
              <input
                type="number"
                min={1}
                value={poolSize}
                onChange={(e) => setPoolSize(Number(e.target.value))}
                className="w-16 px-2 py-1 border border-zinc-300 dark:border-white/10 rounded-lg bg-white dark:bg-white/5 text-zinc-900 dark:text-zinc-100"
              />
            </label>
          </div>
          <button className="px-4 py-2 bg-blue-600 hover:bg-blue-500 dark:bg-blue-500 dark:hover:bg-blue-400 text-white rounded-lg text-sm font-medium">
            Save
          </button>
        </form>
      </section>

      <section className="bg-surface-light dark:bg-surface-dark border border-zinc-200 dark:border-transparent rounded-2xl p-5 mb-6">
        <h2 className="text-sm font-semibold text-emerald-600 dark:text-emerald-400 mb-1">Personalized excerpts</h2>
        <p className="text-xs text-zinc-500 dark:text-zinc-400 mb-3">
          For {criterionId || "…"} ({rubricKey.split("::")[0] || "…"}) — uses the rubric/criterion selected above.
        </p>

        <ul className="divide-y divide-zinc-200 dark:divide-white/5 mb-4">
          {excerpts.map((ex) => (
            <li key={ex.id} className="py-2 flex items-start justify-between gap-3">
              <div>
                <p className="text-sm text-zinc-700 dark:text-zinc-300">&quot;{ex.excerpt_text}&quot;</p>
                <p className="text-xs text-zinc-500 dark:text-zinc-400">
                  score {ex.score} · anchor {ex.anchor_matched} · {ex.source} — {ex.rationale}
                </p>
              </div>
              <button
                onClick={() => deleteExcerpt(ex.id)}
                className="text-xs text-red-600 dark:text-red-400 hover:bg-red-500/10 px-2 py-1 rounded-lg shrink-0"
              >
                Delete
              </button>
            </li>
          ))}
          {excerpts.length === 0 && (
            <li className="py-2 text-sm text-zinc-500 dark:text-zinc-400">No excerpts yet for this criterion.</li>
          )}
        </ul>

        <form onSubmit={addExcerpt} className="space-y-2">
          <textarea
            className="w-full px-3 py-2 border border-zinc-300 dark:border-white/10 rounded-lg bg-white dark:bg-white/5 text-zinc-900 dark:text-zinc-100"
            placeholder="Source essay text (the full essay this excerpt is quoted from)"
            value={sourceEssayText}
            onChange={(e) => setSourceEssayText(e.target.value)}
          />
          <textarea
            className="w-full px-3 py-2 border border-zinc-300 dark:border-white/10 rounded-lg bg-white dark:bg-white/5 text-zinc-900 dark:text-zinc-100"
            placeholder="Excerpt text — must appear word-for-word in the source essay text above"
            value={excerptText}
            onChange={(e) => setExcerptText(e.target.value)}
          />
          <div className="flex gap-4">
            <label className="flex items-center gap-2 text-sm text-zinc-700 dark:text-zinc-300">
              Score
              <input
                type="number"
                min={0}
                max={5}
                value={score}
                onChange={(e) => setScore(Number(e.target.value))}
                className="w-16 px-2 py-1 border border-zinc-300 dark:border-white/10 rounded-lg bg-white dark:bg-white/5 text-zinc-900 dark:text-zinc-100"
              />
            </label>
            <label className="flex items-center gap-2 text-sm text-zinc-700 dark:text-zinc-300">
              Anchor matched
              <input
                type="number"
                min={0}
                max={5}
                value={anchorMatched}
                onChange={(e) => setAnchorMatched(Number(e.target.value))}
                className="w-16 px-2 py-1 border border-zinc-300 dark:border-white/10 rounded-lg bg-white dark:bg-white/5 text-zinc-900 dark:text-zinc-100"
              />
            </label>
          </div>
          <textarea
            className="w-full px-3 py-2 border border-zinc-300 dark:border-white/10 rounded-lg bg-white dark:bg-white/5 text-zinc-900 dark:text-zinc-100"
            placeholder="Rationale"
            value={rationale}
            onChange={(e) => setRationale(e.target.value)}
          />
          {excerptError && <p className="text-sm text-red-600 dark:text-red-400">{excerptError}</p>}
          <button className="px-4 py-2 bg-blue-600 hover:bg-blue-500 dark:bg-blue-500 dark:hover:bg-blue-400 text-white rounded-lg text-sm font-medium">
            Add excerpt
          </button>
        </form>
      </section>

      <section className="bg-surface-light dark:bg-surface-dark border border-zinc-200 dark:border-transparent rounded-2xl p-5 mb-6">
        <h2 className="text-sm font-semibold text-amber-600 dark:text-amber-400 mb-1">Override patterns</h2>
        <p className="text-xs text-zinc-500 dark:text-zinc-400 mb-3">
          How often you override the AI's personalized score, per criterion — a high rate or a consistent
          direction below is a signal to revisit your grading philosophy underneath.
        </p>
        {overrideRates.length === 0 ? (
          <p className="text-sm text-zinc-500 dark:text-zinc-400">No graded criteria yet.</p>
        ) : (
          <ul className="divide-y divide-zinc-200 dark:divide-white/5">
            {overrideRates.map((c) => (
              <li key={`${c.rubric_id}::${c.rubric_version}::${c.criterion_id}`} className="py-2">
                <div className="flex items-center justify-between">
                  <span className="text-sm text-zinc-800 dark:text-zinc-200 font-medium">
                    {c.criterion_id}
                    {c.dimension && (
                      <span className="text-xs text-zinc-400 dark:text-zinc-500 font-normal"> — {c.dimension}</span>
                    )}
                  </span>
                  <span className="text-sm text-zinc-900 dark:text-zinc-100 font-semibold">
                    {(c.override_rate * 100).toFixed(0)}%{" "}
                    <span className="text-xs text-zinc-500 dark:text-zinc-400 font-normal">
                      ({c.n_overrides} of {c.n_graded})
                    </span>
                  </span>
                </div>
                {c.avg_score_diff !== null && Math.abs(c.avg_score_diff) >= 0.1 && (
                  <p className="text-xs text-zinc-500 dark:text-zinc-400 mt-0.5">
                    You tend to score this {c.avg_score_diff > 0 ? "higher" : "lower"} than the AI (avg{" "}
                    {c.avg_score_diff > 0 ? "+" : ""}
                    {c.avg_score_diff.toFixed(1)}).
                  </p>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="bg-surface-light dark:bg-surface-dark border border-zinc-200 dark:border-transparent rounded-2xl p-5">
        <h2 className="text-sm font-semibold text-purple-600 dark:text-purple-400 mb-3">
          Instructor profile (personalized path only)
        </h2>
        <form onSubmit={saveProfile} className="space-y-3">
          <textarea
            className="w-full px-3 py-2 border border-zinc-300 dark:border-white/10 rounded-lg bg-white dark:bg-white/5 text-zinc-900 dark:text-zinc-100"
            placeholder="Grading philosophy"
            value={gradingPhilosophy}
            onChange={(e) => setGradingPhilosophy(e.target.value)}
          />
          <select
            className="w-full px-3 py-2 border border-zinc-300 dark:border-white/10 rounded-lg bg-white dark:bg-white/5 text-zinc-900 dark:text-zinc-100"
            value={rationaleTone}
            onChange={(e) => setRationaleTone(e.target.value)}
          >
            <option value="">(unset)</option>
            <option value="terse">terse</option>
            <option value="detailed">detailed</option>
            <option value="encouraging">encouraging</option>
            <option value="blunt">blunt</option>
          </select>
          <button className="px-4 py-2 bg-blue-600 hover:bg-blue-500 dark:bg-blue-500 dark:hover:bg-blue-400 text-white rounded-lg text-sm font-medium">
            Save
          </button>
        </form>
      </section>
    </div>
  );
}
