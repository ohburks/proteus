import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { api, ApiError } from "../lib/api";
import type { PathResult, ReviewContract } from "../lib/types";

function PathCard({ title, result }: { title: string; result: PathResult | null }) {
  return (
    <div className="flex-1 bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-lg p-4">
      <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100 mb-2">{title}</h3>
      {!result ? (
        <p className="text-sm text-gray-400 dark:text-gray-500">Not available</p>
      ) : (
        <>
          <div className="flex items-center gap-2 mb-1">
            <p className="text-2xl font-bold text-gray-900 dark:text-gray-100">{result.score}</p>
            {result.high_spread && (
              <span className="px-2 py-0.5 text-xs rounded-full bg-purple-100 text-purple-800 dark:bg-purple-900/40 dark:text-purple-300">
                high spread
              </span>
            )}
          </div>
          <p className="text-xs text-gray-500 dark:text-gray-400 mb-1">anchor matched: {result.anchor_matched}</p>
          <p className="text-xs text-gray-500 dark:text-gray-400 mb-3">
            median of {result.n_passes} passes · spread: {result.spread ?? "n/a"} · confidence:{" "}
            {(result.confidence * 100).toFixed(0)}%
          </p>
          <p className="text-sm text-gray-700 dark:text-gray-300 mb-3">{result.rationale}</p>
          <div className="space-y-2 mb-3">
            {result.evidence.map((e, i) => (
              <blockquote
                key={i}
                className="text-xs border-l-2 border-gray-300 dark:border-gray-700 pl-2 text-gray-600 dark:text-gray-400"
              >
                "{e.quote}" — {e.reasoning}
              </blockquote>
            ))}
          </div>
          <details className="text-xs text-gray-500 dark:text-gray-400">
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

  if (!data) return <p className="p-6 text-gray-500 dark:text-gray-400">Loading…</p>;

  return (
    <div className="max-w-4xl mx-auto px-6 py-8 bg-gray-50 dark:bg-gray-950 min-h-[calc(100vh-3.5rem)]">
      <h1 className="text-xl font-semibold text-gray-900 dark:text-gray-100 mb-1">{criterionId}</h1>
      {data.divergence && (
        <p className="text-sm text-gray-500 dark:text-gray-400 mb-6">
          score diff: {data.divergence.score_diff ?? "n/a"} · anchor mismatch: {String(data.divergence.anchor_mismatch)} ·
          {data.divergence.exceeds_threshold ? " exceeds divergence threshold" : " within threshold"}
        </p>
      )}

      <div className="flex gap-4 mb-6">
        <PathCard title="Personalized (output)" result={data.personalized} />
        <PathCard title="Exemplar (reference)" result={data.exemplar} />
      </div>

      {data.current_override && (
        <div className="mb-6 bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800 rounded-lg p-4">
          <p className="text-sm text-blue-900 dark:text-blue-200 font-medium">
            Current override: {data.current_override.new_score} — {data.current_override.new_rationale}
          </p>
        </div>
      )}

      {error && <p className="text-sm text-red-600 dark:text-red-400 mb-3">{error}</p>}

      <form onSubmit={submitOverride} className="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-lg p-4 space-y-3">
        <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100">Override</h3>
        <div className="flex items-center gap-2">
          <label className="text-sm text-gray-700 dark:text-gray-300">Score</label>
          <input
            type="number"
            min={0}
            max={5}
            value={newScore}
            onChange={(e) => setNewScore(Number(e.target.value))}
            className="w-16 px-2 py-1 border border-gray-300 dark:border-gray-700 rounded bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100"
          />
        </div>
        <textarea
          className="w-full px-3 py-2 border border-gray-300 dark:border-gray-700 rounded bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100"
          placeholder="Rationale (required — becomes retrievable precedent)"
          value={newRationale}
          onChange={(e) => setNewRationale(e.target.value)}
        />
        <div className="flex gap-2">
          <button
            type="submit"
            disabled={busy}
            className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 dark:bg-indigo-500 dark:hover:bg-indigo-400 text-white rounded text-sm font-medium disabled:opacity-50"
          >
            Save override
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={adoptExemplar}
            className="px-4 py-2 border border-gray-300 dark:border-gray-700 text-gray-700 dark:text-gray-300 rounded text-sm font-medium hover:bg-gray-50 dark:hover:bg-gray-800 disabled:opacity-50"
          >
            Adopt exemplar
          </button>
        </div>
      </form>
    </div>
  );
}
