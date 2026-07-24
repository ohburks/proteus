import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { api, ApiError } from "../lib/api";
import type { PathResult, ReviewContract } from "../lib/types";
import { PageHeader, cardClass, helpClass, inputClass, numberClass, primaryBtn, titleClass } from "../components/ui";

const pill = "px-2.5 py-0.5 text-xs font-medium rounded-full";

// One grading path (personalized output vs. exemplar reference). Both variants
// share the same surface so the two are directly comparable side by side; the
// output path is marked with a blue ring + tag rather than an inverted card.
function PathCard({
  variant,
  result,
  anchorText,
}: {
  variant: "output" | "reference";
  result: PathResult | null;
  anchorText?: string;
}) {
  const isOutput = variant === "output";
  return (
    <div className={`flex-1 min-w-0 ${cardClass} ${isOutput ? "ring-1 ring-blue-500/40" : ""}`}>
      <div className="flex items-center justify-between gap-2 mb-3">
        <h3 className={titleClass}>{isOutput ? "Personalized" : "Exemplar"}</h3>
        <span
          className={`${pill} ${
            isOutput
              ? "bg-blue-500/15 text-blue-700 dark:text-blue-400"
              : "bg-zinc-500/15 text-zinc-600 dark:text-zinc-400"
          }`}
        >
          {isOutput ? "OUTPUT" : "REFERENCE"}
        </span>
      </div>

      {!result ? (
        <p className={helpClass}>Not available</p>
      ) : (
        <>
          <div className="flex items-baseline gap-2 mb-2">
            {typeof result.score === "number" ? (
              <span className="text-3xl font-bold text-zinc-900 dark:text-zinc-100">{result.score}</span>
            ) : (
              <span className="text-lg font-semibold text-zinc-500 dark:text-zinc-400">no evidence</span>
            )}
            {result.high_spread && (
              <span className={`${pill} bg-purple-500/15 text-purple-700 dark:text-purple-400`}>high spread</span>
            )}
          </div>

          <p className="text-xs text-zinc-500 dark:text-zinc-400 mb-1">anchor matched: {result.anchor_matched}</p>
          <p className="text-xs text-zinc-500 dark:text-zinc-400 mb-3">
            median of {result.n_passes} pass{result.n_passes === 1 ? "" : "es"} · spread: {result.spread ?? "n/a"}
            {/* Pass stability (1 - spread/5 over N passes) only means something
                with more than one pass; with n_passes=1 it's trivially 1.0. Never
                shown as a percentage — that reads as "confidence the score is
                correct," which this doesn't measure. */}
            {result.n_passes > 1 && <> · stability: {result.pass_stability.toFixed(2)}</>}
          </p>

          {anchorText && (
            <p className="text-xs italic text-zinc-600 dark:text-zinc-400 mb-3">{anchorText}</p>
          )}

          <p className="text-sm text-zinc-700 dark:text-zinc-300 mb-3">{result.rationale}</p>

          {result.evidence.length > 0 && (
            <div className="space-y-2 mb-3">
              {result.evidence.map((e, i) => (
                <blockquote
                  key={i}
                  className="text-xs border-l-2 border-zinc-300 dark:border-white/10 pl-2 text-zinc-600 dark:text-zinc-400"
                >
                  "{e.quote}" — {e.reasoning}
                </blockquote>
              ))}
            </div>
          )}

          <details className="text-xs text-zinc-500 dark:text-zinc-400">
            <summary className="cursor-pointer select-none">
              All {result.passes.length} raw pass{result.passes.length === 1 ? "" : "es"}
            </summary>
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

function anchorTextFor(result: PathResult | null, anchors?: Record<string, string>): string | undefined {
  if (!result || typeof result.score !== "number" || !anchors) return undefined;
  // Aggregate scores are multi-pass medians and can be fractional (e.g. 3.5);
  // anchors are keyed by whole point "0".."5", so round the same way the
  // override field seeding below does.
  return anchors[String(Math.round(result.score))];
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
        // The personalized score is a multi-pass median and can be fractional
        // (e.g. 3.5); the override field is an integer 0-5, so round before
        // seeding it — sending 3.5 would be rejected by the backend (422).
        if (typeof d.personalized?.score === "number") setNewScore(Math.round(d.personalized.score));
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

  if (!data) {
    return (
      <div className="min-h-[calc(100vh-3.5rem)] bg-app-light dark:bg-app-dark">
        <PageHeader title={criterionId ?? "Review"} />
        <p className="max-w-3xl mx-auto px-6 py-8 text-sm text-zinc-500 dark:text-zinc-400">Loading…</p>
      </div>
    );
  }

  const divergent = data.divergence?.exceeds_threshold;

  return (
    <div className="min-h-[calc(100vh-3.5rem)] bg-app-light dark:bg-app-dark">
      <PageHeader
        title={criterionId ?? "Review"}
        right={
          data.divergence ? (
            <span
              className={`${pill} ${
                divergent
                  ? "bg-amber-500/15 text-amber-700 dark:text-amber-400"
                  : "bg-zinc-500/15 text-zinc-600 dark:text-zinc-400"
              }`}
            >
              {divergent ? "Divergent" : "Within threshold"}
            </span>
          ) : undefined
        }
      />

      <div className="max-w-3xl mx-auto px-6 py-6">
        {data.criterion && (
          <p className="text-sm text-zinc-600 dark:text-zinc-400 mb-3">{data.criterion.statement}</p>
        )}

        {data.divergence && (
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 mb-6">
            <span className="text-xs text-zinc-500 dark:text-zinc-400">
              Score diff: {data.divergence.score_diff ?? "n/a"}
            </span>
            {data.divergence.anchor_mismatch && (
              <span className={`${pill} bg-amber-500/15 text-amber-700 dark:text-amber-400`}>anchor mismatch</span>
            )}
            {data.divergence.no_evidence_asymmetry && (
              <span className={`${pill} bg-amber-500/15 text-amber-700 dark:text-amber-400`}>no-evidence asymmetry</span>
            )}
          </div>
        )}

        <div className="flex flex-col sm:flex-row gap-4 mb-6">
          <PathCard
            variant="output"
            result={data.personalized}
            anchorText={anchorTextFor(data.personalized, data.criterion?.anchors)}
          />
          <PathCard
            variant="reference"
            result={data.exemplar}
            anchorText={anchorTextFor(data.exemplar, data.criterion?.anchors)}
          />
        </div>

        {data.current_override && (
          <div className="mb-6 bg-blue-500/10 border border-blue-500/20 rounded-2xl p-4">
            <p className="text-sm text-blue-700 dark:text-blue-300 font-medium">
              Current override: {data.current_override.new_score} — {data.current_override.new_rationale}
            </p>
          </div>
        )}

        {error && <p className="text-sm text-red-600 dark:text-red-400 mb-3">{error}</p>}

        <form onSubmit={submitOverride} className={`${cardClass} space-y-3`}>
          <h3 className={titleClass}>Override</h3>
          <div className="flex items-center gap-2">
            <label className="text-sm text-zinc-700 dark:text-zinc-300">Score</label>
            <input
              type="number"
              min={0}
              max={5}
              value={newScore}
              onChange={(e) => setNewScore(Number(e.target.value))}
              className={numberClass}
            />
          </div>
          <textarea
            className={inputClass}
            placeholder="Rationale (required — becomes retrievable precedent)"
            value={newRationale}
            onChange={(e) => setNewRationale(e.target.value)}
          />
          <div className="flex gap-2">
            <button type="submit" disabled={busy} className={`${primaryBtn} disabled:opacity-50`}>
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
    </div>
  );
}
