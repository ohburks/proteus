import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api, ApiError, streamLines } from "../lib/api";
import type { Essay } from "../lib/types";

export function AssignmentPage() {
  const { assignmentId } = useParams<{ assignmentId: string }>();
  const navigate = useNavigate();
  const [essays, setEssays] = useState<Essay[]>([]);
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
    if (!text.trim() || !assignmentId) return;
    await api.post<Essay>("/api/essays", { assignment_id: assignmentId, text });
    setText("");
    refresh();
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
    }
  }

  return (
    <div className="max-w-3xl mx-auto px-6 py-8 bg-gray-50 dark:bg-gray-950 min-h-[calc(100vh-3.5rem)]">
      <h1 className="text-xl font-semibold text-gray-900 dark:text-gray-100 mb-6">Essays</h1>

      <form onSubmit={createEssay} className="mb-6 bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-lg p-4 space-y-2">
        <textarea
          className="w-full h-32 px-3 py-2 border border-gray-300 dark:border-gray-700 rounded bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100"
          placeholder="Paste essay text"
          value={text}
          onChange={(e) => setText(e.target.value)}
        />
        <button className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 dark:bg-indigo-500 dark:hover:bg-indigo-400 text-white rounded text-sm font-medium">
          Add essay
        </button>
      </form>

      {/* pb-7: room for the absolutely-positioned key-status label, which
          renders into this bottom padding (constant height — no shift). */}
      <div className="mb-6 bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-lg p-4 pb-7">
        <h2 className="text-sm font-semibold text-gray-900 dark:text-gray-100 mb-2">
          LLM provider (BYOK) — leave blank to use the server-configured default
        </h2>
        <div className="flex gap-2">
          <select
            className="px-2 py-1 border border-gray-300 dark:border-gray-700 rounded bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 text-sm"
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
              className="w-full px-2 py-1 border border-gray-300 dark:border-gray-700 rounded bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 text-sm"
              placeholder="API key (not needed for ollama)"
              type="password"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
            />
            {keyStatus === "checking" && (
              <p className="absolute left-0 top-full mt-0.5 text-xs text-gray-500 dark:text-gray-400">Checking API key…</p>
            )}
            {keyStatus === "valid" && (
              <p className="absolute left-0 top-full mt-0.5 text-xs text-emerald-600 dark:text-emerald-400">✓ API Key Valid</p>
            )}
            {keyStatus === "invalid" && (
              <p className="absolute left-0 top-full mt-0.5 text-xs text-red-600 dark:text-red-400">✗ API Key Invalid</p>
            )}
          </div>
          <input
            className="flex-1 px-2 py-1 border border-gray-300 dark:border-gray-700 rounded bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 text-sm"
            placeholder="model (optional)"
            value={model}
            onChange={(e) => setModel(e.target.value)}
          />
        </div>
      </div>

      {error && <p className="text-sm text-red-600 dark:text-red-400 mb-3">{error}</p>}

      {terminalAssessmentId && (
        <div className="mb-6 border border-amber-400 dark:border-amber-600 rounded-lg overflow-hidden">
          <div className="flex items-center justify-between bg-amber-100 dark:bg-amber-900/40 px-3 py-1.5 border-b border-amber-400 dark:border-amber-600">
            <span className="text-xs font-bold uppercase tracking-wide text-amber-800 dark:text-amber-300">
              ⚠ TESTING ONLY — live grading terminal
            </span>
            <div className="flex items-center gap-2">
              <span className="text-xs text-amber-800 dark:text-amber-300">
                {terminalStatus === "running" && "running…"}
                {terminalStatus === "complete" && "complete"}
                {terminalStatus === "failed" && "failed"}
              </span>
              {terminalStatus !== "running" && (
                <button
                  onClick={() => navigate(`/assessments/${terminalAssessmentId}`)}
                  className="px-2 py-0.5 bg-indigo-600 hover:bg-indigo-500 text-white rounded text-xs font-medium"
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
                className="px-2 py-0.5 border border-amber-400 dark:border-amber-600 text-amber-800 dark:text-amber-300 rounded text-xs"
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

      <ul className="space-y-2">
        {essays.map((e) => (
          <li key={e.id} className="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-lg p-3">
            <p className="text-sm text-gray-700 dark:text-gray-300 line-clamp-2 mb-2">{e.text}</p>
            <div className="flex gap-2">
              <button
                disabled={busy === e.id}
                onClick={() => grade(e.id)}
                className="px-3 py-1 bg-emerald-600 hover:bg-emerald-500 dark:bg-emerald-500 dark:hover:bg-emerald-400 text-white rounded text-xs font-medium disabled:opacity-50"
              >
                {busy === e.id ? "Grading…" : "Grade"}
              </button>
              <button
                onClick={async () => {
                  const past = await api.get<{ id: string }[]>(`/api/assessments?essay_id=${e.id}`);
                  if (past.length) navigate(`/assessments/${past[0].id}`);
                  else setError("No assessments yet for this essay.");
                }}
                className="px-3 py-1 border border-gray-300 dark:border-gray-700 text-gray-700 dark:text-gray-300 rounded text-xs font-medium hover:bg-gray-50 dark:hover:bg-gray-800"
              >
                View latest results
              </button>
            </div>
          </li>
        ))}
        {essays.length === 0 && <li className="text-gray-500 dark:text-gray-400">No essays added this session yet.</li>}
      </ul>
    </div>
  );
}
