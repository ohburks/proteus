import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, ApiError, downloadFile, streamLines } from "../lib/api";
import type { Assignment, Essay, QueueEntry, Student } from "../lib/types";

type UngradedFilter = "all" | "never" | "running" | "failed" | "cancelled";

export function AssignmentPage() {
  const { assignmentId } = useParams<{ assignmentId: string }>();
  const navigate = useNavigate();
  const [essays, setEssays] = useState<Essay[]>([]);
  const [assignment, setAssignment] = useState<Assignment | null>(null);
  const [students, setStudents] = useState<Student[]>([]);
  const [studentId, setStudentId] = useState("");
  const [queue, setQueue] = useState<QueueEntry[]>([]);
  // Client-side ordering of every essay id. The ungraded section renders the
  // ungraded subsequence of this list and drag-and-drop reorders it in place;
  // that order is the sequence "Grade all" fires runs in.
  const [order, setOrder] = useState<string[]>([]);
  const [batchBusy, setBatchBusy] = useState(false);
  const [ungradedFilter, setUngradedFilter] = useState<UngradedFilter>("all");
  const [gradedNeedsReviewOnly, setGradedNeedsReviewOnly] = useState(false);
  const [dragOverId, setDragOverId] = useState<string | null>(null);
  const dragIdRef = useRef<string | null>(null);
  // Set by "Cancel grading" so the sequential grade-all loop stops before
  // starting the next essay (the in-flight run is cancelled separately).
  const cancelBatchRef = useRef(false);
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
  const [terminalStatus, setTerminalStatus] = useState<
    "running" | "complete" | "failed" | "cancelling" | "cancelled" | null
  >(null);
  const terminalEndRef = useRef<HTMLDivElement>(null);
  const [showDetails, setShowDetails] = useState(false);
  const [detailsPromptText, setDetailsPromptText] = useState("");
  const [detailsFormatExpectations, setDetailsFormatExpectations] = useState("");
  const [detailsCriterionEmphasis, setDetailsCriterionEmphasis] = useState("");
  const [detailsCommonPitfalls, setDetailsCommonPitfalls] = useState("");
  const [detailsSaved, setDetailsSaved] = useState(false);

  useEffect(() => {
    terminalEndRef.current?.scrollIntoView({ block: "nearest" });
  }, [terminalLines]);

  useEffect(() => {
    if (!assignmentId) return;
    api
      .get<{
        prompt_text: string | null;
        format_expectations: string | null;
        criterion_emphasis_notes: string | null;
        common_pitfalls: string | null;
      }>(`/api/settings/assignment-profile/${assignmentId}`)
      .then((p) => {
        setDetailsPromptText(p.prompt_text ?? "");
        setDetailsFormatExpectations(p.format_expectations ?? "");
        setDetailsCriterionEmphasis(p.criterion_emphasis_notes ?? "");
        setDetailsCommonPitfalls(p.common_pitfalls ?? "");
      });
  }, [assignmentId]);

  async function saveAssignmentDetails(e: React.FormEvent) {
    e.preventDefault();
    if (!assignmentId) return;
    await api.put(`/api/settings/assignment-profile/${assignmentId}`, {
      prompt_text: detailsPromptText || null,
      format_expectations: detailsFormatExpectations || null,
      criterion_emphasis_notes: detailsCriterionEmphasis || null,
      common_pitfalls: detailsCommonPitfalls || null,
    });
    setDetailsSaved(true);
    setTimeout(() => setDetailsSaved(false), 2000);
  }

  // Pre-fill provider/model from the instructor's saved default (M10) so
  // returning to grade doesn't require re-selecting them every time. The
  // functional updater means a slow response can't clobber typing that
  // already happened.
  useEffect(() => {
    api
      .get<{ default_llm_provider: string | null; default_llm_model: string | null }>(
        "/api/settings/instructor-profile",
      )
      .then((p) => {
        setProvider((cur) => cur || p.default_llm_provider || "");
        setModel((cur) => cur || p.default_llm_model || "");
      });
  }, []);

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

  // Keep `order` in sync with the essays that exist: preserve the current order,
  // append any newly-added essays at the end, and drop any that were deleted.
  useEffect(() => {
    setOrder((prev) => {
      const ids = essays.map((e) => e.id);
      const kept = prev.filter((id) => ids.includes(id));
      const added = ids.filter((id) => !kept.includes(id));
      return [...kept, ...added];
    });
  }, [essays]);

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
        (status) =>
          setTerminalStatus(
            status === "complete" ? "complete" : status === "cancelled" ? "cancelled" : "failed",
          ),
      );
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Grading failed");
      setTerminalStatus("failed");
    } finally {
      setBusy(null);
      refreshQueue();
    }
  }

  // Signal the backend to stop an in-progress run. The row moves to 'cancelled'
  // only once the grading thread reaches its next criterion checkpoint, so
  // reflect the interim "cancelling…" state optimistically and let the queue
  // poll (or the live SSE 'done' event) confirm the terminal status.
  async function cancel(assessmentId: string) {
    setError(null);
    try {
      await api.post(`/api/assessments/${assessmentId}/cancel`);
      if (terminalAssessmentId === assessmentId && terminalStatus === "running") {
        setTerminalStatus("cancelling");
      }
      refreshQueue();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to cancel grading");
    }
  }

  async function deleteEssay(id: string) {
    if (!confirm("Delete this essay? This permanently deletes its grading history. This cannot be undone.")) return;
    try {
      await api.del(`/api/essays/${id}`);
      refresh();
      refreshQueue();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to delete essay");
    }
  }

  function statusOf(essayId: string): QueueEntry["status"] {
    return queue.find((q) => q.essay_id === essayId)?.status ?? null;
  }
  function entryOf(essayId: string): QueueEntry | undefined {
    return queue.find((q) => q.essay_id === essayId);
  }
  // "Graded" means the latest assessment completed. Anything else — never
  // graded, running, failed, cancelled, or being re-graded right now — sits in
  // the ungraded queue.
  const isGraded = (id: string) => statusOf(id) === "complete";
  const isRunning = (id: string) => statusOf(id) === "running" || statusOf(id) === "pending";

  const ungradedIds = order.filter((id) => !isGraded(id));
  const gradedIds = order.filter((id) => isGraded(id));
  const gradeableIds = ungradedIds.filter((id) => !isRunning(id));
  const gradingInProgress = busy !== null || batchBusy;
  const anyActive = batchBusy || queue.some((q) => q.status === "running" || q.status === "pending");

  // Display-only: narrows which ungraded rows render, never what "Grade
  // all"/gradeAll() targets — that stays scoped to every gradeable essay
  // regardless of the filter, so the button's count never silently
  // diverges from what it actually does.
  const filteredUngradedIds = ungradedIds.filter((id) => {
    if (ungradedFilter === "all") return true;
    const s = statusOf(id);
    if (ungradedFilter === "never") return s === null;
    if (ungradedFilter === "running") return s === "running" || s === "pending";
    return s === ungradedFilter; // "failed" | "cancelled"
  });

  // Display-only, same reasoning as filteredUngradedIds above — no bulk
  // action reads gradedIds directly, so there's nothing for this filter to
  // silently de-scope.
  const filteredGradedIds = gradedIds.filter((id) => {
    if (!gradedNeedsReviewOnly) return true;
    return entryOf(id)?.needs_review ?? false;
  });

  // Drag-and-drop reorder of the ungraded queue: move the dragged essay to just
  // before the row it was dropped on, within the master `order` list.
  function handleDrop(targetId: string) {
    const src = dragIdRef.current;
    dragIdRef.current = null;
    setDragOverId(null);
    if (!src || src === targetId) return;
    setOrder((prev) => {
      const next = prev.filter((id) => id !== src);
      const idx = next.indexOf(targetId);
      if (idx === -1) return prev;
      next.splice(idx, 0, src);
      return next;
    });
  }

  // Grade every ungraded essay in queue order, one at a time (each with its own
  // live terminal). Snapshot the ids up front so reorders/new essays mid-run
  // don't change the batch. "Cancel grading" stops the loop between essays.
  async function gradeAll() {
    const ids = gradeableIds;
    if (ids.length === 0) return;
    cancelBatchRef.current = false;
    setBatchBusy(true);
    try {
      for (const id of ids) {
        if (cancelBatchRef.current) break;
        await grade(id);
      }
    } finally {
      setBatchBusy(false);
      cancelBatchRef.current = false;
      refreshQueue();
    }
  }

  // Cancel the run happening now and halt the batch. Prefer the assessment the
  // live terminal is showing; fall back to whatever the queue reports running.
  async function cancelGrading() {
    cancelBatchRef.current = true;
    if (terminalAssessmentId && terminalStatus === "running") {
      await cancel(terminalAssessmentId);
      return;
    }
    const running = queue.find((q) => q.status === "running" || q.status === "pending");
    if (running?.latest_assessment_id) await cancel(running.latest_assessment_id);
  }

  function studentName(essayId: string): string {
    const essay = essays.find((e) => e.id === essayId);
    const student = essay ? students.find((s) => s.id === essay.student_id) : undefined;
    return student ? student.display_name : "Unlinked essay";
  }

  return (
    <div className="max-w-3xl mx-auto px-6 py-8 bg-app-light dark:bg-app-dark min-h-[calc(100vh-3.5rem)]">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-xl font-semibold text-zinc-900 dark:text-zinc-100">Essays</h1>
        <div className="flex items-center gap-4">
          <button
            onClick={async () => {
              try {
                await downloadFile(`/api/assignments/${assignmentId}/export.csv`, `${assignment?.name ?? "assignment"}_scores.csv`);
              } catch (err) {
                setError(err instanceof ApiError ? err.message : "Failed to export CSV");
              }
            }}
            className="text-sm text-blue-600 dark:text-blue-400 hover:underline"
          >
            Export CSV
          </button>
          <Link to={`/assignments/${assignmentId}/breakdown`} className="text-sm text-blue-600 dark:text-blue-400 hover:underline">
            Class breakdown →
          </Link>
        </div>
      </div>

      <div className="mb-6 bg-surface-light dark:bg-surface-dark border border-zinc-200 dark:border-transparent rounded-2xl p-5">
        <button
          type="button"
          onClick={() => setShowDetails((v) => !v)}
          className="flex items-center justify-between w-full text-left"
        >
          <h2 className="text-sm font-semibold text-blue-600 dark:text-blue-400">Assignment details</h2>
          <span className="text-xs text-zinc-400 dark:text-zinc-500">{showDetails ? "Hide" : "Edit"}</span>
        </button>
        {showDetails && (
          <form onSubmit={saveAssignmentDetails} className="space-y-2 mt-3">
            <textarea
              className="w-full px-3 py-2 border border-zinc-300 dark:border-white/10 rounded-lg bg-white dark:bg-white/5 text-zinc-900 dark:text-zinc-100"
              placeholder="Assignment prompt text (fed to both grading paths)"
              value={detailsPromptText}
              onChange={(e) => setDetailsPromptText(e.target.value)}
            />
            <textarea
              className="w-full px-3 py-2 border border-zinc-300 dark:border-white/10 rounded-lg bg-white dark:bg-white/5 text-zinc-900 dark:text-zinc-100"
              placeholder="Format expectations — fed to both grading paths"
              value={detailsFormatExpectations}
              onChange={(e) => setDetailsFormatExpectations(e.target.value)}
            />
            <textarea
              className="w-full px-3 py-2 border border-zinc-300 dark:border-white/10 rounded-lg bg-white dark:bg-white/5 text-zinc-900 dark:text-zinc-100"
              placeholder="Criterion emphasis notes — fed to both grading paths"
              value={detailsCriterionEmphasis}
              onChange={(e) => setDetailsCriterionEmphasis(e.target.value)}
            />
            <textarea
              className="w-full px-3 py-2 border border-zinc-300 dark:border-white/10 rounded-lg bg-white dark:bg-white/5 text-zinc-900 dark:text-zinc-100"
              placeholder="Common pitfalls"
              value={detailsCommonPitfalls}
              onChange={(e) => setDetailsCommonPitfalls(e.target.value)}
            />
            {detailsSaved && <p className="text-sm text-green-600 dark:text-green-400">Saved.</p>}
            <button className="px-4 py-2 bg-blue-600 hover:bg-blue-500 dark:bg-blue-500 dark:hover:bg-blue-400 text-white rounded-lg text-sm font-medium">
              Save
            </button>
          </form>
        )}
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
          Insert LLM API key here | {" "}
          <Link to="/settings" className="underline hover:no-underline">
            Settings
          </Link>{" "}
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
            <option value="tamu">tamu</option>
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

      {error && (
        <p className="text-sm text-red-600 dark:text-red-400 mb-3">
          {error === "No LLM provider configured." ? (
            <>
              No LLM provider configured —{" "}
              <Link to="/settings" className="underline hover:no-underline">
                set a default in Settings
              </Link>
              , or fill in a one-off key above.
            </>
          ) : (
            error
          )}
        </p>
      )}

      {terminalAssessmentId && (
        <div className="mb-6 border border-amber-500/30 rounded-2xl overflow-hidden">
          <div className="flex items-center justify-between bg-amber-500/15 px-3 py-1.5 border-b border-amber-500/30">
            <span className="text-xs font-bold uppercase tracking-wide text-amber-700 dark:text-amber-400">
              ⚠ TESTING ONLY — live grading terminal
            </span>
            <div className="flex items-center gap-2">
              <span className="text-xs text-amber-700 dark:text-amber-400">
                {terminalStatus === "running" && "running…"}
                {terminalStatus === "cancelling" && "cancelling…"}
                {terminalStatus === "cancelled" && "cancelled"}
                {terminalStatus === "complete" && "complete"}
                {terminalStatus === "failed" && "failed"}
              </span>
              {terminalStatus === "running" && (
                <button
                  onClick={() => cancel(terminalAssessmentId)}
                  className="px-2 py-0.5 border border-red-300 dark:border-red-500/30 text-red-600 dark:text-red-400 rounded-lg text-xs font-medium hover:bg-red-500/10"
                >
                  Cancel
                </button>
              )}
              {terminalStatus !== "running" && terminalStatus !== "cancelling" && (
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

      {/* ── Ungraded queue ─────────────────────────────────────────────── */}
      <section className="mb-8">
        <div className="flex items-center justify-between mb-2">
          <h2 className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">
            Ungraded queue ({ungradedIds.length})
          </h2>
          <div className="flex items-center gap-2">
            <select
              value={ungradedFilter}
              onChange={(e) => setUngradedFilter(e.target.value as UngradedFilter)}
              className="px-2 py-1 border border-zinc-300 dark:border-white/10 rounded-lg bg-white dark:bg-white/5 text-zinc-900 dark:text-zinc-100 text-xs"
            >
              <option value="all">All</option>
              <option value="never">Never graded</option>
              <option value="running">Running</option>
              <option value="failed">Failed</option>
              <option value="cancelled">Cancelled</option>
            </select>
            <button
              onClick={gradeAll}
              disabled={gradingInProgress || gradeableIds.length === 0}
              className="px-3 py-1 bg-green-600 hover:bg-green-500 dark:bg-green-500 dark:hover:bg-green-400 text-white rounded-lg text-xs font-medium disabled:opacity-50"
            >
              {batchBusy ? "Grading…" : `Grade all (${gradeableIds.length})`}
            </button>
            {anyActive && (
              <button
                onClick={cancelGrading}
                className="px-3 py-1 border border-red-300 dark:border-red-500/30 text-red-600 dark:text-red-400 rounded-lg text-xs font-medium hover:bg-red-500/10"
              >
                Cancel grading
              </button>
            )}
          </div>
        </div>

        {ungradedIds.length === 0 ? (
          <p className="text-sm text-zinc-500 dark:text-zinc-400">No ungraded essays.</p>
        ) : filteredUngradedIds.length === 0 ? (
          <p className="text-sm text-zinc-500 dark:text-zinc-400">No essays match this filter.</p>
        ) : (
          <>
            <ul className="space-y-2">
              {filteredUngradedIds.map((id) => {
                const essay = essays.find((e) => e.id === id);
                if (!essay) return null;
                const status = statusOf(id);
                const entry = entryOf(id);
                const running = isRunning(id);
                return (
                  <li
                    key={id}
                    draggable={!gradingInProgress}
                    onDragStart={() => {
                      dragIdRef.current = id;
                    }}
                    onDragOver={(e) => {
                      e.preventDefault();
                      if (dragOverId !== id) setDragOverId(id);
                    }}
                    onDrop={() => handleDrop(id)}
                    onDragEnd={() => {
                      dragIdRef.current = null;
                      setDragOverId(null);
                    }}
                    className={`bg-surface-light dark:bg-surface-dark border rounded-2xl p-4 ${
                      gradingInProgress ? "" : "cursor-move"
                    } ${
                      dragOverId === id
                        ? "border-blue-500 dark:border-blue-400"
                        : "border-zinc-200 dark:border-transparent"
                    }`}
                  >
                    <div className="flex items-start gap-2">
                      <span
                        className="mt-0.5 text-zinc-400 dark:text-zinc-500 select-none"
                        aria-hidden="true"
                        title="Drag to reorder"
                      >
                        ⠿
                      </span>
                      <div className="flex-1">
                        <div className="flex items-center gap-2 flex-wrap mb-1">
                          <p className="text-xs text-zinc-500 dark:text-zinc-400">{studentName(id)}</p>
                          {status === null && (
                            <span className="px-2 py-0.5 text-xs font-medium rounded-full bg-zinc-500/15 text-zinc-600 dark:text-zinc-400">
                              ungraded
                            </span>
                          )}
                          {running && (
                            <span className="px-2.5 py-0.5 text-xs font-medium rounded-full bg-blue-500/15 text-blue-700 dark:text-blue-400">
                              grading…
                            </span>
                          )}
                          {status === "failed" && (
                            <span className="px-2.5 py-0.5 text-xs font-medium rounded-full bg-pink-500/15 text-pink-700 dark:text-pink-400">
                              failed
                            </span>
                          )}
                          {status === "cancelled" && (
                            <span className="px-2.5 py-0.5 text-xs font-medium rounded-full bg-zinc-500/15 text-zinc-600 dark:text-zinc-400">
                              cancelled
                            </span>
                          )}
                        </div>
                        <p className="text-sm text-zinc-700 dark:text-zinc-300 line-clamp-2 mb-2">{essay.text}</p>
                        <div className="flex gap-2">
                          <button
                            disabled={gradingInProgress || running}
                            onClick={() => grade(id)}
                            className="px-3 py-1 bg-green-600 hover:bg-green-500 dark:bg-green-500 dark:hover:bg-green-400 text-white rounded-lg text-xs font-medium disabled:opacity-50"
                          >
                            {busy === id ? "Grading…" : "Grade"}
                          </button>
                          {running && entry?.latest_assessment_id && (
                            <button
                              onClick={() => cancel(entry.latest_assessment_id!)}
                              className="px-3 py-1 border border-red-300 dark:border-red-500/30 text-red-600 dark:text-red-400 rounded-lg text-xs font-medium hover:bg-red-500/10"
                            >
                              Cancel
                            </button>
                          )}
                          {entry?.latest_assessment_id && (
                            <button
                              onClick={() => navigate(`/assessments/${entry.latest_assessment_id}`)}
                              className="px-3 py-1 border border-zinc-300 dark:border-white/10 text-zinc-700 dark:text-zinc-300 rounded-lg text-xs font-medium hover:bg-black/[0.03] dark:hover:bg-white/5"
                            >
                              View latest results
                            </button>
                          )}
                          <button
                            onClick={() => deleteEssay(id)}
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
            </ul>
            <p className="text-xs text-zinc-500 dark:text-zinc-400 mt-2">
              Drag rows to set the order essays are graded in.
            </p>
          </>
        )}
      </section>

      {/* ── Graded ─────────────────────────────────────────────────────── */}
      <section>
        <div className="flex items-center justify-between mb-2">
          <h2 className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">
            Graded ({gradedIds.length})
          </h2>
          <label className="flex items-center gap-1.5 text-xs text-zinc-600 dark:text-zinc-400">
            <input
              type="checkbox"
              checked={gradedNeedsReviewOnly}
              onChange={(e) => setGradedNeedsReviewOnly(e.target.checked)}
            />
            Needs review only
          </label>
        </div>
        {gradedIds.length === 0 ? (
          <p className="text-sm text-zinc-500 dark:text-zinc-400">No graded essays yet.</p>
        ) : filteredGradedIds.length === 0 ? (
          <p className="text-sm text-zinc-500 dark:text-zinc-400">No essays match this filter.</p>
        ) : (
          <ul className="space-y-2">
            {filteredGradedIds.map((id) => {
              const essay = essays.find((e) => e.id === id);
              if (!essay) return null;
              const entry = entryOf(id);
              return (
                <li
                  key={id}
                  className="bg-surface-light dark:bg-surface-dark border border-zinc-200 dark:border-transparent rounded-2xl p-4"
                >
                  <div className="flex items-center gap-2 flex-wrap mb-1">
                    <p className="text-xs text-zinc-500 dark:text-zinc-400">{studentName(id)}</p>
                    <span className="px-2.5 py-0.5 text-xs font-medium rounded-full bg-green-500/15 text-green-700 dark:text-green-400">
                      graded
                    </span>
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
                    {entry?.needs_review && (
                      <span className="px-2.5 py-0.5 text-xs font-medium rounded-full bg-red-500/15 text-red-700 dark:text-red-400">
                        needs review
                      </span>
                    )}
                  </div>
                  <p className="text-sm text-zinc-700 dark:text-zinc-300 line-clamp-2 mb-2">{essay.text}</p>
                  <div className="flex gap-2">
                    <button
                      disabled={gradingInProgress}
                      onClick={() => grade(id)}
                      className="px-3 py-1 bg-blue-600 hover:bg-blue-500 dark:bg-blue-500 dark:hover:bg-blue-400 text-white rounded-lg text-xs font-medium disabled:opacity-50"
                    >
                      {busy === id ? "Regrading…" : "Regrade"}
                    </button>
                    <button
                      onClick={() => {
                        if (entry?.latest_assessment_id) navigate(`/assessments/${entry.latest_assessment_id}`);
                        else setError("No assessments yet for this essay.");
                      }}
                      className="px-3 py-1 border border-zinc-300 dark:border-white/10 text-zinc-700 dark:text-zinc-300 rounded-lg text-xs font-medium hover:bg-black/[0.03] dark:hover:bg-white/5"
                    >
                      View results
                    </button>
                    <button
                      onClick={() => deleteEssay(id)}
                      className="px-3 py-1 border border-red-300 dark:border-red-500/30 text-red-600 dark:text-red-400 rounded-lg text-xs font-medium hover:bg-red-500/10"
                    >
                      Delete
                    </button>
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </section>
    </div>
  );
}
