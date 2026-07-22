import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { api, ApiError } from "../lib/api";
import type { PathResult, ReviewContract } from "../lib/types";

function PathCard({ title, result, highlight }: { title: string; result: PathResult | null; highlight?: boolean }) {
  return (
    <div
      className={
        highlight
          ? "flex-1 bg-blue-600 dark:bg-blue-600 rounded-2xl p-6 text-white"
          : "flex-1 bg-surface-light dark:bg-surface-dark border border-zinc-200 dark:border-transparent rounded-2xl p-6"
      }
    >
      <h3 className={highlight ? "text-sm font-semibold text-white/90 mb-2" : "text-sm font-semibold text-zinc-900 dark:text-zinc-100 mb-2"}>
        {title}
      </h3>
      {!result ? (
        <p className={highlight ? "text-sm text-white/70" : "text-sm text-zinc-400 dark:text-zinc-500"}>Not available</p>
      ) : (
        <>
          <div className="flex items-center gap-2 mb-1">
            <p className={highlight ? "text-3xl font-bold text-white" : "text-3xl font-bold text-zinc-900 dark:text-zinc-100"}>
              {result.score}
            </p>
            {result.high_spread && (
              <span
                className={
                  highlight
                    ? "px-2.5 py-0.5 text-xs font-medium rounded-full bg-white/20 text-white"
                    : "px-2.5 py-0.5 text-xs font-medium rounded-full bg-purple-500/15 text-purple-700 dark:text-purple-400"
                }
              >
                high spread
              </span>
            )}
          </div>
          <p className={highlight ? "text-xs text-white/70 mb-1" : "text-xs text-zinc-500 dark:text-zinc-400 mb-1"}>
            anchor matched: {result.anchor_matched}
          </p>
          <p className={highlight ? "text-xs text-white/70 mb-3" : "text-xs text-zinc-500 dark:text-zinc-400 mb-3"}>
            median of {result.n_passes} passes · spread: {result.spread ?? "n/a"} · confidence:{" "}
            {(result.confidence * 100).toFixed(0)}%
          </p>
          <p className={highlight ? "text-sm text-white/90 mb-3" : "text-sm text-zinc-700 dark:text-zinc-300 mb-3"}>
            {result.rationale}
          </p>
          <div className="space-y-2 mb-3">
            {result.evidence.map((e, i) => (
              <blockquote
                key={i}
                className={
                  highlight
                    ? "text-xs border-l-2 border-white/30 pl-2 text-white/80"
                    : "text-xs border-l-2 border-zinc-300 dark:border-white/10 pl-2 text-zinc-600 dark:text-zinc-400"
                }
              >
                "{e.quote}" — {e.reasoning}
              </blockquote>
            ))}
          </div>
          <details className={highlight ? "text-xs text-white/70" : "text-xs text-zinc-500 dark:text-zinc-400"}>
            <summary className="cursor-pointer select-none">All {result.passes.length} raw passes</summary>
            <ul className="mt-2 space-y-1">
              {result.passes.map((p) => (
                <li key={p.pass_index}>
                  pass {p.pass_index + 1}: score={p.score}, anchor={p.anchor_matched}, self-confidence=
                  {(p.confidence * 100).toFixed(0)}%
                </li>
              ))}
            </ul>
          </details>
        </>
      )}
    </div>
  );
}

export function ReviewPage() {
  const { assessmentId, criterionId } = useParams<{ assessmentId: string; criterionId: string }>();
  const [data, setData] = useState<ReviewContract | null>(null);
  const [newScore, setNewScore] = useState(0);
  const [newRationale, setNewRationale] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  function refresh() {
    if (!assessmentId || !criterionId) return;
    api
      .get<ReviewContract>(`/api/assessments/${assessmentId}/criteria/${criterionId}/review`)
      .then((d) => {
        setData(d);
        if (typeof d.personalized?.score === "number") setNewScore(d.personalized.score);
      });
  }

  useEffect(refresh, [assessmentId, criterionId]);

  async function submitOverride(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (!newRationale.trim()) {
      setError("Rationale is required — it becomes retrievable precedent.");
      return;
    }
    setBusy(true);
    try {
      await api.post(`/api/assessments/${assessmentId}/criteria/${criterionId}/override`, {
        new_score: newScore,
        new_rationale: newRationale,
      });
      refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Override failed");
    } finally {
      setBusy(false);
    }
  }

  async function adoptExemplar() {
    setBusy(true);
    setError(null);
    try {
      await api.post(`/api/assessments/${assessmentId}/criteria/${criterionId}/adopt-exemplar`, {});
      refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Adopt failed");
    } finally {
      setBusy(false);
    }
  }

  if (!data) return <p className="p-6 text-zinc-500 dark:text-zinc-400">Loading…</p>;

  return (
    <div className="max-w-4xl mx-auto px-6 py-8 bg-app-light dark:bg-app-dark min-h-[calc(100vh-3.5rem)]">
      <h1 className="text-xl font-semibold text-zinc-900 dark:text-zinc-100 mb-1">{criterionId}</h1>
      {data.divergence && (
        <p className="text-sm text-zinc-500 dark:text-zinc-400 mb-6">
          score diff: {data.divergence.score_diff ?? "n/a"} · anchor mismatch: {String(data.divergence.anchor_mismatch)} ·
          {data.divergence.exceeds_threshold ? " exceeds divergence threshold" : " within threshold"}
        </p>
      )}

      <div className="flex gap-4 mb-6">
        <PathCard title="Personalized (output)" result={data.personalized} highlight />
        <PathCard title="Exemplar (reference)" result={data.exemplar} />
      </div>

      {data.current_override && (
        <div className="mb-6 bg-blue-500/10 border border-blue-500/20 rounded-2xl p-4">
          <p className="text-sm text-blue-700 dark:text-blue-300 font-medium">
            Current override: {data.current_override.new_score} — {data.current_override.new_rationale}
          </p>
        </div>
      )}

      {error && <p className="text-sm text-red-600 dark:text-red-400 mb-3">{error}</p>}

      <form onSubmit={submitOverride} className="bg-surface-light dark:bg-surface-dark border border-zinc-200 dark:border-transparent rounded-2xl p-5 space-y-3">
        <h3 className="text-sm font-semibold text-blue-600 dark:text-blue-400">Override</h3>
        <div className="flex items-center gap-2">
          <label className="text-sm text-zinc-700 dark:text-zinc-300">Score</label>
          <input
            type="number"
            min={0}
            max={5}
            value={newScore}
            onChange={(e) => setNewScore(Number(e.target.value))}
            className="w-16 px-2 py-1 border border-zinc-300 dark:border-white/10 rounded-lg bg-white dark:bg-white/5 text-zinc-900 dark:text-zinc-100"
          />
        </div>
        <textarea
          className="w-full px-3 py-2 border border-zinc-300 dark:border-white/10 rounded-lg bg-white dark:bg-white/5 text-zinc-900 dark:text-zinc-100"
          placeholder="Rationale (required — becomes retrievable precedent)"
          value={newRationale}
          onChange={(e) => setNewRationale(e.target.value)}
        />
        <div className="flex gap-2">
          <button
            type="submit"
            disabled={busy}
            className="px-4 py-2 bg-blue-600 hover:bg-blue-500 dark:bg-blue-500 dark:hover:bg-blue-400 text-white rounded-lg text-sm font-medium disabled:opacity-50"
          >
            Save override
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={adoptExemplar}
            className="px-4 py-2 border border-zinc-300 dark:border-white/10 text-zinc-700 dark:text-zinc-300 rounded-lg text-sm font-medium hover:bg-black/[0.03] dark:hover:bg-white/5 disabled:opacity-50"
          >
            Adopt exemplar
          </button>
        </div>
      </form>
    </div>
  );
}
