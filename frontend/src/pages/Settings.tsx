import { useEffect, useState } from "react";
import { api } from "../lib/api";
import type { Rubric } from "../lib/types";
import {
  PageHeader,
  Tabs,
  cardClass,
  helpClass,
  inputClass,
  labelClass,
  numberClass,
  primaryBtn,
  selectClass,
  titleClass,
} from "../components/ui";

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

type Tab = "profile" | "criterion" | "insights";

export function SettingsPage() {
  const [rubrics, setRubrics] = useState<RubricSummary[]>([]);
  const [rubricKey, setRubricKey] = useState("");
  const [rubric, setRubric] = useState<Rubric | null>(null);
  const [criterionId, setCriterionId] = useState("");
  const [spreadThreshold, setSpreadThreshold] = useState(1);
  const [poolSize, setPoolSize] = useState(5);
  const [gradingPhilosophy, setGradingPhilosophy] = useState("");
  const [rationaleTone, setRationaleTone] = useState("");
  const [defaultProvider, setDefaultProvider] = useState("");
  const [defaultModel, setDefaultModel] = useState("");
  // Not editable here, but must round-trip through the save: the PUT upserts
  // every profile column, so omitting these would wipe the stored value.
  const [deprioritizedCriteria, setDeprioritizedCriteria] = useState<string[] | null>(null);
  const [prioritizedCriteria, setPrioritizedCriteria] = useState<string[] | null>(null);
  const [saved, setSaved] = useState<string | null>(null);
  const [overrideRates, setOverrideRates] = useState<OverrideRateEntry[]>([]);
  const [activeTab, setActiveTab] = useState<Tab>("profile");

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
        prioritized_criteria: string[] | null;
        rationale_tone: string | null;
        default_llm_provider: string | null;
        default_llm_model: string | null;
      }>("/api/settings/instructor-profile")
      .then((p) => {
        setGradingPhilosophy(p.grading_philosophy ?? "");
        setRationaleTone(p.rationale_tone ?? "");
        setDeprioritizedCriteria(p.deprioritized_criteria);
        setPrioritizedCriteria(p.prioritized_criteria);
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
      .get<{ spread_threshold: number; min_scoped_pool_size: number }>(
        `/api/settings/thresholds?rubric_id=${rubric_id}&criterion_id=${criterionId}`,
      )
      .then((t) => {
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

  async function saveProfile(e: React.FormEvent) {
    e.preventDefault();
    await api.put("/api/settings/instructor-profile", {
      grading_philosophy: gradingPhilosophy || null,
      rationale_tone: rationaleTone || null,
      deprioritized_criteria: deprioritizedCriteria,
      prioritized_criteria: prioritizedCriteria,
      default_llm_provider: defaultProvider || null,
      default_llm_model: defaultModel || null,
    });
    setSaved("Instructor profile saved.");
    setTimeout(() => setSaved(null), 2000);
  }

  return (
    <div className="min-h-[calc(100vh-3.5rem)] bg-app-light dark:bg-app-dark">
      <PageHeader
        title="Settings"
        right={saved ? <span className="text-sm text-green-600 dark:text-green-400">{saved}</span> : undefined}
      />

      <div className="max-w-3xl mx-auto px-6 py-6">
        <Tabs
          className="mb-6"
          active={activeTab}
          onChange={setActiveTab}
          tabs={[
            { key: "profile", label: "Profile" },
            { key: "criterion", label: "Criterion tuning" },
            { key: "insights", label: "Insights" },
          ]}
        />

        {/* ── Profile: instructor voice + LLM defaults, one save ──────────── */}
        {activeTab === "profile" && (
          <section className={cardClass}>
            <h2 className={titleClass}>Instructor profile</h2>
            <p className={`${helpClass} mt-1 mb-4`}>
              Shapes professor-calibrated grading and pre-fills the grading page's provider/model. Your API
              key is never stored here — it's entered per session on the grading page (or comes from the server
              default).
            </p>
            <form onSubmit={saveProfile} className="space-y-4">
              <div>
                <label className={labelClass}>Grading philosophy</label>
                <textarea
                  className={inputClass}
                  rows={6}
                  placeholder="How you approach grading — tone, priorities, what you weight"
                  value={gradingPhilosophy}
                  onChange={(e) => setGradingPhilosophy(e.target.value)}
                />
              </div>
              <div className="flex flex-wrap gap-4">
                <div>
                  <label className={labelClass}>Rationale tone</label>
                  <select
                    className={selectClass}
                    value={rationaleTone}
                    onChange={(e) => setRationaleTone(e.target.value)}
                  >
                    <option value="">(unset)</option>
                    <option value="terse">terse</option>
                    <option value="detailed">detailed</option>
                    <option value="encouraging">encouraging</option>
                    <option value="blunt">blunt</option>
                  </select>
                </div>
                <div>
                  <label className={labelClass}>Default LLM provider</label>
                  <select
                    className={selectClass}
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
                </div>
                <div className="flex-1 min-w-[10rem]">
                  <label className={labelClass}>Default model (optional)</label>
                  <input
                    className={inputClass}
                    placeholder="e.g. gpt-4o-mini"
                    value={defaultModel}
                    onChange={(e) => setDefaultModel(e.target.value)}
                  />
                </div>
              </div>
              <button className={primaryBtn}>Save profile</button>
            </form>
          </section>
        )}

        {/* ── Criterion tuning: shared selector governs both cards below ──── */}
        {activeTab === "criterion" && (
          <div className="space-y-4">
            <div className="bg-blue-500/[0.06] dark:bg-blue-500/10 border border-blue-500/20 rounded-2xl p-4">
              <p className="text-xs font-medium text-blue-700 dark:text-blue-300 mb-2">
                Editing calibrated grading settings for:
              </p>
              <div className="flex flex-wrap gap-2">
                <select className={selectClass} value={rubricKey} onChange={(e) => setRubricKey(e.target.value)}>
                  {rubrics.map((r) => (
                    <option key={`${r.rubric_id}::${r.version}`} value={`${r.rubric_id}::${r.version}`}>
                      {r.rubric_id} v{r.version}
                    </option>
                  ))}
                </select>
                <select className={selectClass} value={criterionId} onChange={(e) => setCriterionId(e.target.value)}>
                  {rubric?.criteria.map((c) => (
                    <option key={c.criterionId} value={c.criterionId}>
                      {c.criterionId} — {c.dimension}
                    </option>
                  ))}
                </select>
              </div>
            </div>

            <section className={cardClass}>
              <h2 className={titleClass}>Stability &amp; retrieval settings</h2>
              <p className={`${helpClass} mt-1 mb-4`}>
                Spread flags inconsistent repeated samples. Pool size controls how many professor-scored
                examples are retrieved for this criterion.
              </p>
              <form onSubmit={saveThresholds} className="space-y-4">
                <div className="flex flex-wrap gap-6">
                  <label className="flex items-center gap-2 text-sm text-zinc-700 dark:text-zinc-300">
                    Spread
                    <input
                      type="number"
                      min={0}
                      max={5}
                      step={0.1}
                      value={spreadThreshold}
                      onChange={(e) => setSpreadThreshold(Number(e.target.value))}
                      className={numberClass}
                    />
                  </label>
                  <label className="flex items-center gap-2 text-sm text-zinc-700 dark:text-zinc-300">
                    Professor examples per criterion
                    <input
                      type="number"
                      min={1}
                      max={20}
                      value={poolSize}
                      onChange={(e) => setPoolSize(Number(e.target.value))}
                      className={numberClass}
                    />
                  </label>
                </div>
                <button className={primaryBtn}>Save thresholds</button>
              </form>
            </section>

          </div>
        )}

        {/* ── Insights: read-only override analytics ─────────────────────── */}
        {activeTab === "insights" && (
          <section className={cardClass}>
            <h2 className={titleClass}>Override patterns</h2>
            <p className={`${helpClass} mt-1 mb-4`}>
              How often you override the calibrated score, per criterion — a high rate or a consistent direction
              is a signal to add more professor examples or clarify your grading philosophy.
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
        )}
      </div>
    </div>
  );
}
