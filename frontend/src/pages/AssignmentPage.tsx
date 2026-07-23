import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, ApiError, streamLines } from "../lib/api";
import type { Assignment, Essay, QueueEntry, Student } from "../lib/types";

export function AssignmentPage() {
  const { assignmentId } = useParams<{ assignmentId: string }>();
  const navigate = useNavigate();
  const [essays, setEssays] = useState<Essay[]>([]);
  const [assignment, setAssignment] = useState<Assignment | null>(null);
  const [students, setStudents] = useState<Student[]>([]);
  const [studentId, setStudentId] = useState("");
  const [queue, setQueue] = useState<QueueEntry[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [launched, setLaunched] = useState<Set<string>>(new Set());
  const [bulkBusy, setBulkBusy] = useState(false);
  const [text, setText] = useState("");
  const [provider, setProvider] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [model, setModel] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [keyStatus, setKeyStatus] = useState<"checking" | "valid" | "invalid" | null>(null);
  const keyCheckSeq = useRef(0);
  const [terminalLines, setTerminalLines] = useState<string[]>([]);
  const [terminalAssessmentId, setTerminalAssessmentId] = useState<string | null>(null);
  const [terminalStatus, setTerminalStatus] = useState<"running" | "complete" | "failed" | null>(null);
  const terminalEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    terminalEndRef.current?.scrollIntoView({ block: "nearest" });
  }, [terminalLines]);

  function refresh() {
    if (!assignmentId) return;
    api.get<Essay[]>(`/api/essays?assignment_id=${assignmentId}`).then(setEssays);
  }

  useEffect(refresh, [assignmentId]);

  useEffect(() => {
    if (!assignmentId) return;
    api.get<Assignment>(`/api/assignments/${assignmentId}`).then(setAssignment);
  }, [assignmentId]);

  useEffect(() => {
    if (!assignment) return;
    api.get<Student[]>(`/api/students?course_id=${assignment.course_id}`).then(setStudents);
  }, [assignment]);

  function refreshQueue() {
    if (!assignmentId) return;
    api.get<QueueEntry[]>(`/api/assignments/${assignmentId}/queue`).then(setQueue);
  }

  useEffect(refreshQueue, [assignmentId]);

  // Poll the aggregate queue (not per-essay SSE) while anything is in
  // progress, so bulk grading doesn't require opening N live streams.
  useEffect(() => {
    const anyActive = queue.some((q) => q.status === "running" || q.status === "pending");
    if (!anyActive) return;
    const id = setInterval(refreshQueue, 2000);
    return () => clearInterval(id);
  }, [queue]);

  // Debounced live check of the BYOK key: waits for typing to settle, then
  // asks the backend to make a token-free authenticated call. The sequence
  // counter drops stale responses so a slow check can't overwrite a newer one.
  useEffect(() => {
    if (!provider || (!apiKey && provider !== "ollama")) {
      setKeyStatus(null);
      return;
    }
    const seq = ++keyCheckSeq.current;
    setKeyStatus("checking");
    const timer = setTimeout(async () => {
      try {
        const res = await api.post<{ valid: boolean }>("/api/assessments/validate-byok", {
          provider,
          api_key: apiKey || null,
          model: model || null,
        });
        if (keyCheckSeq.current === seq) setKeyStatus(res.valid ? "valid" : "invalid");
      } catch {
        if (keyCheckSeq.current === seq) setKeyStatus("invalid");
      }
    }, 600);
    return () => clearTimeout(timer);
  }, [provider, apiKey, model]);

  async function createEssay(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (!assignmentId) return;
    if (!text.trim()) {
      setError("Essay text is required.");
      return;
    }
    if (!studentId) {
      setError("Select a student.");
      return;
    }
    try {
      await api.post<Essay>("/api/essays", { assignment_id: assignmentId, student_id: studentId, text });
      setText("");
      setStudentId("");
      refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to add essay");
    }
  }

  async function grade(essayId: string) {
    setError(null);
    setBusy(essayId);
    setTerminalLines([]);
    setTerminalStatus("running");
    try {
      const byok = provider ? { provider, api_key: apiKey || null, model: model || null } : undefined;
      const assessment = await api.post<{ id: string }>("/api/assessments", { essay_id: essayId, byok });
      setTerminalAssessmentId(assessment.id);
      await streamLines(
        `/api/assessments/${assessment.id}/stream`,
        (line) => setTerminalLines((prev) => [...prev, line]),
        (status) => setTerminalStatus(status === "complete" ? "complete" : "failed"),
      );
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Grading failed");
      setTerminalStatus("failed");
    } finally {
      setBusy(null);
      refreshQueue();
    }
  }

  function toggleSelected(essayId: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(essayId)) next.delete(essayId);
      else next.add(essayId);
      return next;
    });
  }

  function selectAllUngraded() {
    const ungraded = queue.filter((q) => q.status === null || q.status === "failed").map((q) => q.essay_id);
    setSelected(new Set(ungraded));
  }

  // Staging (checking a box / "Select all ungraded") only ever touches
  // `selected` — nothing is sent to the backend until "Start grading" below
  // is clicked. `launched` tracks ids from the most recent bulk-grade call so
  // the queue panel can keep showing them as grading/graded/failed even
  // after `selected` is cleared for the next staging round.
  function queueRowState(essayId: string): "staged" | "grading" | "graded" | "failed" {
    if (launched.has(essayId)) {
      const entry = queue.find((q) => q.essay_id === essayId);
      if (entry?.status === "complete") return "graded";
      if (entry?.status === "failed") return "failed";
      return "grading";
    }
    return "staged";
  }

  // Sequential, not concurrent: loops the same single-essay grade() (POST +
  // live SSE terminal) one essay at a time, so the queue still shows real
  // terminal output per essay instead of firing them all via bulk-grade with
  // no visibility. grade() already catches its own errors, so one failure
  // doesn't stop the rest of the queue from running.
  async function startGrading() {
    if (!assignmentId || selected.size === 0) return;
    const ids = Array.from(selected);
    setLaunched((prev) => new Set([...prev, ...ids]));
    setSelected(new Set());
    setBulkBusy(true);
    try {
      for (const id of ids) {
        await grade(id);
      }
    } finally {
      setBulkBusy(false);
    }
  }

  // Dismiss staged-but-not-started items and finished ones from the panel —
  // never hides a batch that's still actively grading.
  function clearQueuePanel() {
    setSelected(new Set());
    setLaunched((prev) => {
      const next = new Set(prev);
      for (const id of prev) {
        const entry = queue.find((q) => q.essay_id === id);
        if (!entry || entry.status === "complete" || entry.status === "failed") next.delete(id);
      }
      return next;
    });
  }

  return (
    <div className="max-w-3xl mx-auto px-6 py-8 bg-app-light dark:bg-app-dark min-h-[calc(100vh-3.5rem)]">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-xl font-semibold text-zinc-900 dark:text-zinc-100">Essays</h1>
        <Link to={`/assignments/${assignmentId}/breakdown`} className="text-sm text-blue-600 dark:text-blue-400 hover:underline">
          Class breakdown →
        </Link>
      </div>

      <form onSubmit={createEssay} className="mb-6 bg-surface-light dark:bg-surface-dark border border-zinc-200 dark:border-transparent rounded-2xl p-5 space-y-2">
        <select
          className="w-full px-2 py-1 border border-zinc-300 dark:border-white/10 rounded-lg bg-white dark:bg-white/5 text-zinc-900 dark:text-zinc-100 text-sm"
          value={studentId}
          onChange={(e) => setStudentId(e.target.value)}
        >
          <option value="">Select student…</option>
          {students.map((s) => (
            <option key={s.id} value={s.id}>
              {s.display_name}
            </option>
          ))}
        </select>
        <textarea
          className="w-full h-32 px-3 py-2 border border-zinc-300 dark:border-white/10 rounded-lg bg-white dark:bg-white/5 text-zinc-900 dark:text-zinc-100"
          placeholder="Paste essay text"
          value={text}
          onChange={(e) => setText(e.target.value)}
        />
        <button className="px-4 py-2 bg-blue-600 hover:bg-blue-500 dark:bg-blue-500 dark:hover:bg-blue-400 text-white rounded-lg text-sm font-medium">
          Add essay
        </button>
      </form>

      {/* pb-7: room for the absolutely-positioned key-status label, which
          renders into this bottom padding (constant height — no shift). */}
      <div className="mb-6 bg-surface-light dark:bg-surface-dark border border-zinc-200 dark:border-transparent rounded-2xl p-5 pb-8">
        <h2 className="text-sm font-semibold text-blue-600 dark:text-blue-400 mb-2">
          LLM provider (BYOK) — leave blank to use the server-configured default
        </h2>
        <div className="flex gap-2">
          <select
            className="px-2 py-1 border border-zinc-300 dark:border-white/10 rounded-lg bg-white dark:bg-white/5 text-zinc-900 dark:text-zinc-100 text-sm"
            value={provider}
            onChange={(e) => setProvider(e.target.value)}
          >
            <option value="">server default</option>
            <option value="openai">openai</option>
            <option value="anthropic">anthropic</option>
            <option value="gemini">gemini</option>
            <option value="groq">groq</option>
            <option value="mistral">mistral</option>
            <option value="github">github</option>
            <option value="ollama">ollama</option>
          </select>
          {/* Wrapper is the anchor for the status label: absolutely
              positioned below the key box so showing it renders into the
              card's bottom padding instead of growing the card. */}
          <div className="relative flex-1">
            <input
              className="w-full px-2 py-1 border border-zinc-300 dark:border-white/10 rounded-lg bg-white dark:bg-white/5 text-zinc-900 dark:text-zinc-100 text-sm"
              placeholder="API key (not needed for ollama)"
              type="password"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
            />
            {keyStatus === "checking" && (
              <p className="absolute left-0 top-full mt-0.5 text-xs text-zinc-500 dark:text-zinc-400">Checking API key…</p>
            )}
            {keyStatus === "valid" && (
              <p className="absolute left-0 top-full mt-0.5 text-xs text-green-600 dark:text-green-400">✓ API Key Valid</p>
            )}
            {keyStatus === "invalid" && (
              <p className="absolute left-0 top-full mt-0.5 text-xs text-red-600 dark:text-red-400">✗ API Key Invalid</p>
            )}
          </div>
          <input
            className="flex-1 px-2 py-1 border border-zinc-300 dark:border-white/10 rounded-lg bg-white dark:bg-white/5 text-zinc-900 dark:text-zinc-100 text-sm"
            placeholder="model (optional)"
            value={model}
            onChange={(e) => setModel(e.target.value)}
          />
        </div>
      </div>

      {error && <p className="text-sm text-red-600 dark:text-red-400 mb-3">{error}</p>}

      {terminalAssessmentId && (
        <div className="mb-6 border border-amber-500/30 rounded-2xl overflow-hidden">
          <div className="flex items-center justify-between bg-amber-500/15 px-3 py-1.5 border-b border-amber-500/30">
            <span className="text-xs font-bold uppercase tracking-wide text-amber-700 dark:text-amber-400">
              ⚠ TESTING ONLY — live grading terminal
            </span>
            <div className="flex items-center gap-2">
              <span className="text-xs text-amber-700 dark:text-amber-400">
                {terminalStatus === "running" && "running…"}
                {terminalStatus === "complete" && "complete"}
                {terminalStatus === "failed" && "failed"}
              </span>
              {terminalStatus !== "running" && (
                <button
                  onClick={() => navigate(`/assessments/${terminalAssessmentId}`)}
                  className="px-2 py-0.5 bg-blue-600 hover:bg-blue-500 text-white rounded-lg text-xs font-medium"
                >
                  View results
                </button>
              )}
              <button
                onClick={() => {
                  setTerminalAssessmentId(null);
                  setTerminalLines([]);
                  setTerminalStatus(null);
                }}
                className="px-2 py-0.5 border border-amber-500/30 text-amber-700 dark:text-amber-400 rounded-lg text-xs"
              >
                Close
              </button>
            </div>
          </div>
          <div className="bg-black text-green-400 font-mono text-xs p-3 h-56 overflow-y-auto">
            {terminalLines.map((line, i) => (
              <div key={i} className="whitespace-pre-wrap">{line}</div>
            ))}
            <div ref={terminalEndRef} />
          </div>
        </div>
      )}

      {essays.length > 0 && (
        <div className="flex items-center gap-2 mb-3">
          <button
            onClick={selectAllUngraded}
            className="px-3 py-1 border border-zinc-300 dark:border-white/10 text-zinc-700 dark:text-zinc-300 rounded-lg text-xs font-medium hover:bg-black/[0.03] dark:hover:bg-white/5"
          >
            Select all ungraded
          </button>
          <button
            onClick={() => setSelected(new Set())}
            disabled={selected.size === 0}
            className="px-3 py-1 border border-zinc-300 dark:border-white/10 text-zinc-700 dark:text-zinc-300 rounded-lg text-xs font-medium hover:bg-black/[0.03] dark:hover:bg-white/5 disabled:opacity-50"
          >
            Clear selection
          </button>
        </div>
      )}

      {(selected.size > 0 || launched.size > 0) && (() => {
        const rowIds = Array.from(new Set([...selected, ...launched]));
        const stagedCount = rowIds.filter((id) => queueRowState(id) === "staged").length;
        const runningCount = rowIds.filter((id) => queueRowState(id) === "grading").length;
        const doneCount = rowIds.filter((id) => queueRowState(id) === "graded" || queueRowState(id) === "failed").length;
        return (
          <div className="mb-6 border border-amber-500/30 rounded-2xl overflow-hidden">
            <div className="flex items-center justify-between bg-amber-500/15 px-3 py-1.5 border-b border-amber-500/30">
              <span className="text-xs font-bold uppercase tracking-wide text-amber-700 dark:text-amber-400">
                Grading queue — {stagedCount} staged, {runningCount} grading, {doneCount} done
              </span>
              <div className="flex items-center gap-2">
                <button
                  disabled={bulkBusy || stagedCount === 0}
                  onClick={startGrading}
                  className="px-2 py-0.5 bg-green-600 hover:bg-green-500 text-white rounded-lg text-xs font-medium disabled:opacity-50"
                >
                  {bulkBusy ? "Starting…" : `Start grading (${stagedCount})`}
                </button>
                <button
                  onClick={clearQueuePanel}
                  className="px-2 py-0.5 border border-amber-500/30 text-amber-700 dark:text-amber-400 rounded-lg text-xs"
                >
                  Clear
                </button>
              </div>
            </div>
            <ul className="divide-y divide-zinc-200 dark:divide-white/5">
              {rowIds.map((id) => {
                const essay = essays.find((e) => e.id === id);
                const student = essay ? students.find((s) => s.id === essay.student_id) : undefined;
                const state = queueRowState(id);
                return (
                  <li key={id} className="flex items-center justify-between px-3 py-1.5 text-xs">
                    <span className="text-zinc-700 dark:text-zinc-300">
                      {student ? student.display_name : "Unlinked essay"}
                    </span>
                    <span className="flex items-center gap-2">
                      <span
                        className={
                          state === "staged"
                            ? "text-zinc-500 dark:text-zinc-400"
                            : state === "grading"
                              ? "text-blue-700 dark:text-blue-400"
                              : state === "graded"
                                ? "text-green-700 dark:text-green-400"
                                : "text-pink-700 dark:text-pink-400"
                        }
                      >
                        {state === "grading" ? "grading…" : state}
                      </span>
                      {state === "staged" && (
                        <button
                          onClick={() => setSelected((prev) => {
                            const next = new Set(prev);
                            next.delete(id);
                            return next;
                          })}
                          className="text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-200"
                          aria-label="Remove from queue"
                        >
                          ✕
                        </button>
                      )}
                    </span>
                  </li>
                );
              })}
            </ul>
          </div>
        );
      })()}

      <ul className="space-y-2">
        {essays.map((e) => {
          const student = students.find((s) => s.id === e.student_id);
          const entry = queue.find((q) => q.essay_id === e.id);
          return (
          <li key={e.id} className="bg-surface-light dark:bg-surface-dark border border-zinc-200 dark:border-transparent rounded-2xl p-4">
            <div className="flex items-start gap-2 mb-1">
              <input
                type="checkbox"
                checked={selected.has(e.id)}
                onChange={() => toggleSelected(e.id)}
                className="mt-0.5"
              />
              <div className="flex-1">
                <div className="flex items-center gap-2 flex-wrap mb-1">
                  <p className="text-xs text-zinc-500 dark:text-zinc-400">
                    {student ? student.display_name : "Unlinked essay"}
                  </p>
                  {(!entry || entry.status === null) && (
                    <span className="px-2 py-0.5 text-xs font-medium rounded-full bg-zinc-500/15 text-zinc-600 dark:text-zinc-400">
                      ungraded
                    </span>
                  )}
                  {(entry?.status === "running" || entry?.status === "pending") && (
                    <span className="px-2.5 py-0.5 text-xs font-medium rounded-full bg-blue-500/15 text-blue-700 dark:text-blue-400">
                      grading…
                    </span>
                  )}
                  {entry?.status === "complete" && (
                    <span className="px-2.5 py-0.5 text-xs font-medium rounded-full bg-green-500/15 text-green-700 dark:text-green-400">
                      graded
                    </span>
                  )}
                  {entry?.status === "failed" && (
                    <span className="px-2.5 py-0.5 text-xs font-medium rounded-full bg-pink-500/15 text-pink-700 dark:text-pink-400">
                      failed
                    </span>
                  )}
                  {entry?.exceeds_threshold && (
                    <span className="px-2.5 py-0.5 text-xs font-medium rounded-full bg-amber-500/15 text-amber-700 dark:text-amber-400">
                      divergent
                    </span>
                  )}
                  {entry?.high_spread && (
                    <span className="px-2.5 py-0.5 text-xs font-medium rounded-full bg-purple-500/15 text-purple-700 dark:text-purple-400">
                      high spread
                    </span>
                  )}
                </div>
                <p className="text-sm text-zinc-700 dark:text-zinc-300 line-clamp-2 mb-2">{e.text}</p>
                <div className="flex gap-2">
                  <button
                    disabled={busy === e.id}
                    onClick={() => grade(e.id)}
                    className="px-3 py-1 bg-green-600 hover:bg-green-500 dark:bg-green-500 dark:hover:bg-green-400 text-white rounded-lg text-xs font-medium disabled:opacity-50"
                  >
                    {busy === e.id ? "Grading…" : "Grade"}
                  </button>
                  <button
                    onClick={() => {
                      if (entry?.latest_assessment_id) navigate(`/assessments/${entry.latest_assessment_id}`);
                      else setError("No assessments yet for this essay.");
                    }}
                    className="px-3 py-1 border border-zinc-300 dark:border-white/10 text-zinc-700 dark:text-zinc-300 rounded-lg text-xs font-medium hover:bg-black/[0.03] dark:hover:bg-white/5"
                  >
                    View latest results
                  </button>
                  <button
                    onClick={async () => {
                      if (!confirm("Delete this essay? This permanently deletes its grading history. This cannot be undone.")) return;
                      try {
                        await api.del(`/api/essays/${e.id}`);
                        setSelected((prev) => {
                          const next = new Set(prev);
                          next.delete(e.id);
                          return next;
                        });
                        setLaunched((prev) => {
                          const next = new Set(prev);
                          next.delete(e.id);
                          return next;
                        });
                        refresh();
                        refreshQueue();
                      } catch (err) {
                        setError(err instanceof ApiError ? err.message : "Failed to delete essay");
                      }
                    }}
                    className="px-3 py-1 border border-red-300 dark:border-red-500/30 text-red-600 dark:text-red-400 rounded-lg text-xs font-medium hover:bg-red-500/10"
                  >
                    Delete
                  </button>
                </div>
              </div>
            </div>
          </li>
          );
        })}
        {essays.length === 0 && <li className="text-zinc-500 dark:text-zinc-400">No essays added this session yet.</li>}
      </ul>
    </div>
  );
}
