import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, ApiError, downloadFile } from "../lib/api";
import type { Assignment, Course, Student } from "../lib/types";
import {
  Chip,
  OverflowMenu,
  PageHeader,
  Tabs,
  cardClass,
  headerBtn,
  helpClass,
  inputClass,
  primaryBtn,
  rowClass,
  titleClass,
} from "../components/ui";

interface RubricSummary {
  rubric_id: string;
  version: string;
  genre: string;
  notes: string;
}

type Tab = "assignments" | "students" | "profile";

export function CoursePage() {
  const { courseId } = useParams<{ courseId: string }>();
  const [courseName, setCourseName] = useState<string | null>(null);
  const [assignments, setAssignments] = useState<Assignment[]>([]);
  const [students, setStudents] = useState<Student[]>([]);
  const [rubrics, setRubrics] = useState<RubricSummary[]>([]);
  const [assignmentName, setAssignmentName] = useState("");
  const [rubricKey, setRubricKey] = useState("");
  const [promptText, setPromptText] = useState("");
  const [formatExpectations, setFormatExpectations] = useState("");
  const [criterionEmphasisNotes, setCriterionEmphasisNotes] = useState("");
  const [commonPitfalls, setCommonPitfalls] = useState("");
  const [studentName, setStudentName] = useState("");
  const [studentExternalRef, setStudentExternalRef] = useState("");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editExternalRef, setEditExternalRef] = useState("");
  const [cohortLevel, setCohortLevel] = useState("");
  const [curriculumTexts, setCurriculumTexts] = useState("");
  const [rubricVersionPin, setRubricVersionPin] = useState("");
  const [profileSaved, setProfileSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<Tab>("assignments");
  const [showNewAssignment, setShowNewAssignment] = useState(false);
  const [showAddStudent, setShowAddStudent] = useState(false);

  function refresh() {
    if (!courseId) return;
    api.get<Assignment[]>(`/api/assignments?course_id=${courseId}`).then(setAssignments);
    api.get<Student[]>(`/api/students?course_id=${courseId}`).then(setStudents);
  }

  // The course name isn't returned by any single-course endpoint, so pull the
  // list and pick this one out — just for the header title.
  useEffect(() => {
    api.get<Course[]>("/api/courses").then((cs) => {
      setCourseName(cs.find((c) => c.id === courseId)?.name ?? null);
    });
  }, [courseId]);

  useEffect(() => {
    api.get<RubricSummary[]>("/api/rubrics").then((rs) => {
      setRubrics(rs);
      if (rs.length && !rubricKey) setRubricKey(`${rs[0].rubric_id}::${rs[0].version}`);
    });
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [courseId]);

  useEffect(() => {
    if (!courseId) return;
    api
      .get<{ cohort_level: string | null; curriculum_texts: string[] | null; rubric_version_pin: string | null }>(
        `/api/settings/course-profile/${courseId}`,
      )
      .then((p) => {
        setCohortLevel(p.cohort_level ?? "");
        setCurriculumTexts(p.curriculum_texts ? p.curriculum_texts.join("\n") : "");
        setRubricVersionPin(p.rubric_version_pin ?? "");
      });
  }, [courseId]);

  async function saveCourseProfile(e: React.FormEvent) {
    e.preventDefault();
    if (!courseId) return;
    await api.put(`/api/settings/course-profile/${courseId}`, {
      cohort_level: cohortLevel || null,
      curriculum_texts: curriculumTexts.trim() ? curriculumTexts.split("\n").map((s) => s.trim()).filter(Boolean) : null,
      rubric_version_pin: rubricVersionPin || null,
    });
    setProfileSaved(true);
    setTimeout(() => setProfileSaved(false), 2000);
  }

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
        format_expectations: formatExpectations || null,
        criterion_emphasis_notes: criterionEmphasisNotes || null,
        common_pitfalls: commonPitfalls || null,
      });
      setAssignmentName("");
      setPromptText("");
      setFormatExpectations("");
      setCriterionEmphasisNotes("");
      setCommonPitfalls("");
      setShowNewAssignment(false);
      refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to create assignment");
    }
  }

  async function deleteAssignment(a: Assignment) {
    if (!confirm(`Delete assignment "${a.name}"? This permanently deletes all its essays and grading history. This cannot be undone.`)) return;
    try {
      await api.del(`/api/assignments/${a.id}`);
      refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to delete assignment");
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
      setShowAddStudent(false);
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

  async function removeStudent(s: Student) {
    if (!confirm(`Remove student "${s.display_name}"? Their essays will be unlinked, not deleted.`)) return;
    try {
      await api.del(`/api/students/${s.id}`);
      refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to remove student");
    }
  }

  async function exportCsv() {
    try {
      await downloadFile(`/api/courses/${courseId}/export.csv`, "course_scores.csv");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to export CSV");
    }
  }

  return (
    <div className="min-h-[calc(100vh-3.5rem)] bg-app-light dark:bg-app-dark">
      <PageHeader
        title={courseName ?? "Course"}
        subtitle={`${assignments.length} assignment${assignments.length === 1 ? "" : "s"} · ${students.length} student${
          students.length === 1 ? "" : "s"
        }`}
        right={
          <button onClick={exportCsv} className={headerBtn}>
            Export CSV
          </button>
        }
      />

      <div className="max-w-3xl mx-auto px-6 py-6">
        <Tabs
          className="mb-4"
          active={activeTab}
          onChange={setActiveTab}
          tabs={[
            { key: "assignments", label: `Assignments (${assignments.length})` },
            { key: "students", label: `Students (${students.length})` },
            { key: "profile", label: "Course profile" },
          ]}
        />

        {error && <p className="text-sm text-red-600 dark:text-red-400 mb-4">{error}</p>}

        {/* ── Assignments ────────────────────────────────────────────────── */}
        {activeTab === "assignments" && (
          <section>
            <div className="mb-4">
              <Chip active={showNewAssignment} onClick={() => setShowNewAssignment((v) => !v)}>
                <span className="text-base leading-none">＋</span> New assignment
              </Chip>
            </div>

            {showNewAssignment && (
              <form onSubmit={createAssignment} className={`${cardClass} space-y-2 mb-4`}>
                <input
                  className={inputClass}
                  placeholder="Assignment name"
                  value={assignmentName}
                  onChange={(e) => setAssignmentName(e.target.value)}
                />
                <textarea
                  className={inputClass}
                  placeholder="Assignment prompt text (fed to both grading paths)"
                  value={promptText}
                  onChange={(e) => setPromptText(e.target.value)}
                />
                <textarea
                  className={inputClass}
                  placeholder="Format expectations (e.g. cite at least two sources) — fed to both grading paths"
                  value={formatExpectations}
                  onChange={(e) => setFormatExpectations(e.target.value)}
                />
                <textarea
                  className={inputClass}
                  placeholder="Criterion emphasis notes — fed to both grading paths"
                  value={criterionEmphasisNotes}
                  onChange={(e) => setCriterionEmphasisNotes(e.target.value)}
                />
                <textarea
                  className={inputClass}
                  placeholder="Common pitfalls (e.g. students keep confusing claim vs. counterclaim)"
                  value={commonPitfalls}
                  onChange={(e) => setCommonPitfalls(e.target.value)}
                />
                <select
                  className={inputClass}
                  value={rubricKey}
                  onChange={(e) => setRubricKey(e.target.value)}
                >
                  {rubrics.map((r) => (
                    <option key={`${r.rubric_id}::${r.version}`} value={`${r.rubric_id}::${r.version}`}>
                      {r.rubric_id} v{r.version}
                    </option>
                  ))}
                </select>
                <button className={primaryBtn}>Add assignment</button>
              </form>
            )}

            {assignments.length === 0 ? (
              <p className="text-sm text-zinc-500 dark:text-zinc-400">No assignments yet.</p>
            ) : (
              <ul className="space-y-2">
                {assignments.map((a) => (
                  <li key={a.id} className={`${rowClass} flex items-center justify-between gap-2`}>
                    <Link
                      to={`/assignments/${a.id}`}
                      className="flex-1 min-w-0 text-zinc-800 dark:text-zinc-200 hover:underline"
                    >
                      {a.name}{" "}
                      <span className="text-xs text-zinc-400 dark:text-zinc-500">
                        ({a.rubric_id} v{a.rubric_version})
                      </span>
                    </Link>
                    <OverflowMenu items={[{ label: "Delete", onClick: () => deleteAssignment(a), danger: true }]} />
                  </li>
                ))}
              </ul>
            )}
          </section>
        )}

        {/* ── Students ───────────────────────────────────────────────────── */}
        {activeTab === "students" && (
          <section>
            <div className="mb-4">
              <Chip active={showAddStudent} onClick={() => setShowAddStudent((v) => !v)}>
                <span className="text-base leading-none">＋</span> Add student
              </Chip>
            </div>

            {showAddStudent && (
              <form onSubmit={createStudent} className={`${cardClass} flex gap-2 mb-4`}>
                <input
                  className={`${inputClass} flex-1`}
                  placeholder="Student name"
                  value={studentName}
                  onChange={(e) => setStudentName(e.target.value)}
                />
                <input
                  className="w-40 px-3 py-2 border border-zinc-300 dark:border-white/10 rounded-lg bg-white dark:bg-white/5 text-zinc-900 dark:text-zinc-100 text-sm"
                  placeholder="External ref (optional)"
                  value={studentExternalRef}
                  onChange={(e) => setStudentExternalRef(e.target.value)}
                />
                <button className={`${primaryBtn} shrink-0`}>Add</button>
              </form>
            )}

            {students.length === 0 ? (
              <p className="text-sm text-zinc-500 dark:text-zinc-400">No students yet.</p>
            ) : (
              <ul className="space-y-2">
                {students.map((s) => (
                  <li key={s.id} className={rowClass}>
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0">
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
                      <div className="flex items-center gap-1 shrink-0">
                        <button
                          onClick={() => toggleStudentStatus(s)}
                          className={
                            s.status === "archived"
                              ? "px-3 py-1.5 border border-zinc-300 dark:border-white/10 text-zinc-700 dark:text-zinc-300 rounded-lg text-xs font-medium hover:bg-black/[0.03] dark:hover:bg-white/5"
                              : "px-3 py-1.5 border border-amber-300 dark:border-amber-500/30 text-amber-700 dark:text-amber-400 rounded-lg text-xs font-medium hover:bg-amber-500/10"
                          }
                        >
                          {s.status === "archived" ? "Reactivate" : "Archive"}
                        </button>
                        <OverflowMenu items={[{ label: "Remove", onClick: () => removeStudent(s), danger: true }]} />
                      </div>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </section>
        )}

        {/* ── Course profile ─────────────────────────────────────────────── */}
        {activeTab === "profile" && (
          <section className={cardClass}>
            <h2 className={titleClass}>Course profile</h2>
            <p className={`${helpClass} mt-1 mb-4`}>
              Course-level context fed to the personalized grading path for every assignment in this course.
            </p>
            <form onSubmit={saveCourseProfile} className="space-y-2">
              <input
                className={inputClass}
                placeholder="Cohort level (e.g. 11th grade honors)"
                value={cohortLevel}
                onChange={(e) => setCohortLevel(e.target.value)}
              />
              <textarea
                className={inputClass}
                placeholder="Curriculum texts (one per line)"
                value={curriculumTexts}
                onChange={(e) => setCurriculumTexts(e.target.value)}
              />
              <input
                className={inputClass}
                placeholder="Rubric version pin (optional)"
                value={rubricVersionPin}
                onChange={(e) => setRubricVersionPin(e.target.value)}
              />
              {profileSaved && <p className="text-sm text-green-600 dark:text-green-400">Saved.</p>}
              <button className={primaryBtn}>Save</button>
            </form>
          </section>
        )}
      </div>
    </div>
  );
}
