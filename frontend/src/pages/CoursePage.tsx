import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../lib/api";
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
    if (!assignmentName.trim() || !rubricKey) return;
    const [rubric_id, rubric_version] = rubricKey.split("::");
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
  }

  async function createStudent(e: React.FormEvent) {
    e.preventDefault();
    if (!studentName.trim()) return;
    await api.post("/api/students", { course_id: courseId, display_name: studentName });
    setStudentName("");
    refresh();
  }

  return (
    <div className="max-w-3xl mx-auto px-6 py-8 bg-gray-50 dark:bg-gray-950 min-h-[calc(100vh-3.5rem)]">
      <h1 className="text-xl font-semibold text-gray-900 dark:text-gray-100 mb-6">Assignments</h1>

      <form onSubmit={createAssignment} className="mb-4 bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-lg p-4 space-y-2">
        <input
          className="w-full px-3 py-2 border border-gray-300 dark:border-gray-700 rounded bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100"
          placeholder="Assignment name"
          value={assignmentName}
          onChange={(e) => setAssignmentName(e.target.value)}
        />
        <textarea
          className="w-full px-3 py-2 border border-gray-300 dark:border-gray-700 rounded bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100"
          placeholder="Assignment prompt text (fed to both grading paths)"
          value={promptText}
          onChange={(e) => setPromptText(e.target.value)}
        />
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
        <button className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 dark:bg-indigo-500 dark:hover:bg-indigo-400 text-white rounded text-sm font-medium">
          Add assignment
        </button>
      </form>

      <ul className="divide-y divide-gray-200 dark:divide-gray-800 bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-lg overflow-hidden mb-8">
        {assignments.map((a) => (
          <li key={a.id}>
            <Link to={`/assignments/${a.id}`} className="block px-4 py-3 text-gray-800 dark:text-gray-200 hover:bg-gray-50 dark:hover:bg-gray-800">
              {a.name} <span className="text-xs text-gray-400 dark:text-gray-500">({a.rubric_id} v{a.rubric_version})</span>
            </Link>
          </li>
        ))}
        {assignments.length === 0 && <li className="px-4 py-3 text-gray-500 dark:text-gray-400">No assignments yet.</li>}
      </ul>

      <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100 mb-3">Students</h2>
      <form onSubmit={createStudent} className="flex gap-2 mb-3">
        <input
          className="flex-1 px-3 py-2 border border-gray-300 dark:border-gray-700 rounded bg-white dark:bg-gray-900 text-gray-900 dark:text-gray-100"
          placeholder="Student name"
          value={studentName}
          onChange={(e) => setStudentName(e.target.value)}
        />
        <button className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 dark:bg-indigo-500 dark:hover:bg-indigo-400 text-white rounded text-sm font-medium">
          Add student
        </button>
      </form>
      <ul className="flex flex-wrap gap-2">
        {students.map((s) => (
          <li key={s.id} className="px-3 py-1 text-sm bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-full text-gray-700 dark:text-gray-300">
            {s.display_name}
          </li>
        ))}
      </ul>
    </div>
  );
}
