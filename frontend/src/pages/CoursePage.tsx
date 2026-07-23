import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, ApiError } from "../lib/api";
import type { Assignment, Student } from "../lib/types";

interface RubricSummary {
  rubric_id: string;
  version: string;
  genre: string;
  notes: string;
}

export function CoursePage() {
  const { courseId } = useParams<{ courseId: string }>();
  const [assignments, setAssignments] = useState<Assignment[]>([]);
  const [students, setStudents] = useState<Student[]>([]);
  const [rubrics, setRubrics] = useState<RubricSummary[]>([]);
  const [assignmentName, setAssignmentName] = useState("");
  const [rubricKey, setRubricKey] = useState("");
  const [promptText, setPromptText] = useState("");
  const [studentName, setStudentName] = useState("");
  const [studentExternalRef, setStudentExternalRef] = useState("");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editExternalRef, setEditExternalRef] = useState("");
  const [error, setError] = useState<string | null>(null);

  function refresh() {
    if (!courseId) return;
    api.get<Assignment[]>(`/api/assignments?course_id=${courseId}`).then(setAssignments);
    api.get<Student[]>(`/api/students?course_id=${courseId}`).then(setStudents);
  }

  useEffect(() => {
    api.get<RubricSummary[]>("/api/rubrics").then((rs) => {
      setRubrics(rs);
      if (rs.length && !rubricKey) setRubricKey(`${rs[0].rubric_id}::${rs[0].version}`);
    });
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [courseId]);

  async function createAssignment(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (!assignmentName.trim()) {
      setError("Assignment name is required.");
      return;
    }
    if (!rubricKey) {
      setError("Select a rubric.");
      return;
    }
    const [rubric_id, rubric_version] = rubricKey.split("::");
    try {
      await api.post("/api/assignments", {
        course_id: courseId,
        name: assignmentName,
        rubric_id,
        rubric_version,
        prompt_text: promptText || null,
      });
      setAssignmentName("");
      setPromptText("");
      refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to create assignment");
    }
  }

  async function createStudent(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (!studentName.trim()) {
      setError("Student name is required.");
      return;
    }
    try {
      await api.post("/api/students", {
        course_id: courseId,
        display_name: studentName,
        external_ref: studentExternalRef.trim() || null,
      });
      setStudentName("");
      setStudentExternalRef("");
      refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to add student");
    }
  }

  async function saveExternalRef(s: Student) {
    try {
      await api.put(`/api/students/${s.id}`, {
        external_ref: editExternalRef.trim() || null,
        status: s.status,
      });
      setEditingId(null);
      refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to update student");
    }
  }

  async function toggleStudentStatus(s: Student) {
    const nextStatus = s.status === "archived" ? "active" : "archived";
    if (nextStatus === "archived" && !confirm(`Archive "${s.display_name}"? They'll stay on the roster but be marked inactive.`)) return;
    try {
      await api.put(`/api/students/${s.id}`, { external_ref: s.external_ref, status: nextStatus });
      refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to update student");
    }
  }

  return (
    <div className="max-w-3xl mx-auto px-6 py-8 bg-app-light dark:bg-app-dark min-h-[calc(100vh-3.5rem)]">
      <h1 className="text-xl font-semibold text-zinc-900 dark:text-zinc-100 mb-6">Assignments</h1>

      <form onSubmit={createAssignment} className="mb-4 bg-surface-light dark:bg-surface-dark border border-zinc-200 dark:border-transparent rounded-2xl p-5 space-y-2">
        <input
          className="w-full px-3 py-2 border border-zinc-300 dark:border-white/10 rounded-lg bg-white dark:bg-white/5 text-zinc-900 dark:text-zinc-100"
          placeholder="Assignment name"
          value={assignmentName}
          onChange={(e) => setAssignmentName(e.target.value)}
        />
        <textarea
          className="w-full px-3 py-2 border border-zinc-300 dark:border-white/10 rounded-lg bg-white dark:bg-white/5 text-zinc-900 dark:text-zinc-100"
          placeholder="Assignment prompt text (fed to both grading paths)"
          value={promptText}
          onChange={(e) => setPromptText(e.target.value)}
        />
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
        <button className="px-4 py-2 bg-blue-600 hover:bg-blue-500 dark:bg-blue-500 dark:hover:bg-blue-400 text-white rounded-lg text-sm font-medium">
          Add assignment
        </button>
      </form>

      {error && <p className="text-sm text-red-600 dark:text-red-400 mb-4">{error}</p>}

      <ul className="divide-y divide-zinc-200 dark:divide-white/5 bg-surface-light dark:bg-surface-dark border border-zinc-200 dark:border-transparent rounded-2xl overflow-hidden mb-8">
        {assignments.map((a) => (
          <li key={a.id} className="flex items-center justify-between px-4 py-3 hover:bg-black/[0.03] dark:hover:bg-white/5">
            <Link to={`/assignments/${a.id}`} className="flex-1 text-zinc-800 dark:text-zinc-200">
              {a.name} <span className="text-xs text-zinc-400 dark:text-zinc-500">({a.rubric_id} v{a.rubric_version})</span>
            </Link>
            <button
              onClick={async () => {
                if (!confirm(`Delete assignment "${a.name}"? This permanently deletes all its essays and grading history. This cannot be undone.`)) return;
                try {
                  await api.del(`/api/assignments/${a.id}`);
                  refresh();
                } catch (err) {
                  setError(err instanceof ApiError ? err.message : "Failed to delete assignment");
                }
              }}
              className="ml-3 px-2 py-1 text-xs text-red-600 dark:text-red-400 hover:bg-red-500/10 rounded-lg"
            >
              Delete
            </button>
          </li>
        ))}
        {assignments.length === 0 && <li className="px-4 py-3 text-zinc-500 dark:text-zinc-400">No assignments yet.</li>}
      </ul>

      <h2 className="text-lg font-semibold text-purple-600 dark:text-purple-400 mb-3">Students</h2>
      <form onSubmit={createStudent} className="flex gap-2 mb-3">
        <input
          className="flex-1 px-3 py-2 border border-zinc-300 dark:border-white/10 rounded-lg bg-white dark:bg-surface-dark text-zinc-900 dark:text-zinc-100"
          placeholder="Student name"
          value={studentName}
          onChange={(e) => setStudentName(e.target.value)}
        />
        <input
          className="w-40 px-3 py-2 border border-zinc-300 dark:border-white/10 rounded-lg bg-white dark:bg-surface-dark text-zinc-900 dark:text-zinc-100"
          placeholder="External ref (optional)"
          value={studentExternalRef}
          onChange={(e) => setStudentExternalRef(e.target.value)}
        />
        <button className="px-4 py-2 bg-blue-600 hover:bg-blue-500 dark:bg-blue-500 dark:hover:bg-blue-400 text-white rounded-lg text-sm font-medium">
          Add student
        </button>
      </form>
      <ul className="divide-y divide-zinc-200 dark:divide-white/5 bg-surface-light dark:bg-surface-dark border border-zinc-200 dark:border-transparent rounded-2xl overflow-hidden">
        {students.map((s) => (
          <li key={s.id} className="flex items-center justify-between px-4 py-3">
            <div>
              <p className="text-zinc-800 dark:text-zinc-200 font-medium">
                <Link to={`/students/${s.id}/history`} className="hover:underline">
                  {s.display_name}
                </Link>
                {s.status === "archived" && (
                  <span className="ml-2 px-2 py-0.5 text-xs font-medium rounded-full bg-zinc-500/15 text-zinc-600 dark:text-zinc-400">
                    archived
                  </span>
                )}
              </p>
              {editingId === s.id ? (
                <div className="flex items-center gap-1.5 mt-1">
                  <input
                    className="px-2 py-1 text-xs border border-zinc-300 dark:border-white/10 rounded bg-white dark:bg-white/5 text-zinc-900 dark:text-zinc-100"
                    placeholder="External ref"
                    value={editExternalRef}
                    onChange={(e) => setEditExternalRef(e.target.value)}
                    autoFocus
                  />
                  <button onClick={() => saveExternalRef(s)} className="text-xs text-blue-600 dark:text-blue-400 hover:underline">
                    Save
                  </button>
                  <button onClick={() => setEditingId(null)} className="text-xs text-zinc-500 dark:text-zinc-400 hover:underline">
                    Cancel
                  </button>
                </div>
              ) : (
                <p className="text-xs text-zinc-400 dark:text-zinc-500">
                  {s.external_ref ? `Ref: ${s.external_ref}` : "No external ref"}{" "}
                  <button
                    onClick={() => {
                      setEditingId(s.id);
                      setEditExternalRef(s.external_ref ?? "");
                    }}
                    className="text-blue-600 dark:text-blue-400 hover:underline"
                  >
                    Edit
                  </button>
                </p>
              )}
            </div>
            <div className="flex items-center gap-2">
              <button
                onClick={() => toggleStudentStatus(s)}
                className={
                  s.status === "archived"
                    ? "px-3 py-1 border border-zinc-300 dark:border-white/10 text-zinc-700 dark:text-zinc-300 rounded-lg text-xs font-medium hover:bg-black/[0.03] dark:hover:bg-white/5"
                    : "px-3 py-1 border border-amber-300 dark:border-amber-500/30 text-amber-700 dark:text-amber-400 rounded-lg text-xs font-medium hover:bg-amber-500/10"
                }
              >
                {s.status === "archived" ? "Reactivate" : "Archive"}
              </button>
              <button
                onClick={async () => {
                  if (!confirm(`Remove student "${s.display_name}"? Their essays will be unlinked, not deleted.`)) return;
                  try {
                    await api.del(`/api/students/${s.id}`);
                    refresh();
                  } catch (err) {
                    setError(err instanceof ApiError ? err.message : "Failed to remove student");
                  }
                }}
                className="text-zinc-400 hover:text-red-600 dark:hover:text-red-400"
                aria-label={`Remove ${s.display_name}`}
              >
                ✕
              </button>
            </div>
          </li>
        ))}
        {students.length === 0 && <li className="px-4 py-3 text-zinc-500 dark:text-zinc-400">No students yet.</li>}
      </ul>
    </div>
  );
}
