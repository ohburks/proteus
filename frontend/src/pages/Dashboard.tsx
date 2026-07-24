import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { api, ApiError } from "../lib/api";
import type { Course } from "../lib/types";
import { OverflowMenu, PageHeader, inputClass, primaryBtn, rowClass } from "../components/ui";

export function DashboardPage() {
  const { role } = useAuth();
  const [courses, setCourses] = useState<Course[]>([]);
  const [name, setName] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  function refresh() {
    api.get<Course[]>("/api/courses").then(setCourses).finally(() => setLoading(false));
  }

  useEffect(refresh, []);

  async function createCourse(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (!name.trim()) {
      setError("Course name is required.");
      return;
    }
    try {
      await api.post("/api/courses", { name });
      setName("");
      refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to create course");
    }
  }

  async function deleteCourse(c: Course) {
    if (!confirm(`Delete course "${c.name}"? This permanently deletes all its assignments, essays, grading history, and students. This cannot be undone.`)) return;
    try {
      await api.del(`/api/courses/${c.id}`);
      refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to delete course");
    }
  }

  return (
    <div className="min-h-[calc(100vh-3.5rem)] bg-app-light dark:bg-app-dark">
      <PageHeader title="Courses" />
      <div className="max-w-3xl mx-auto px-6 py-6">
        {role === "admin" ? (
          <p className="text-sm text-amber-700 dark:text-amber-400 bg-amber-500/10 border border-amber-500/20 rounded-2xl px-4 py-3 mb-6">
            The admin role is for setup and oversight across instructors — it isn't tied to an
            instructor identity, so it can't own courses directly. Log in as{" "}
            <code className="font-mono">instructor</code>/<code className="font-mono">instruct123</code>{" "}
            to create and manage courses.{" "}
            <Link to="/admin/accounts" className="underline hover:no-underline">
              Manage accounts →
            </Link>
          </p>
        ) : (
          <form onSubmit={createCourse} className="flex gap-2 mb-4">
            <input
              className={`${inputClass} flex-1`}
              placeholder="New course name"
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
            <button className={`${primaryBtn} shrink-0`}>Add course</button>
          </form>
        )}
        {error && <p className="text-sm text-red-600 dark:text-red-400 mb-4">{error}</p>}

        {loading ? (
          <p className="text-zinc-500 dark:text-zinc-400">Loading…</p>
        ) : courses.length === 0 ? (
          <p className="text-zinc-500 dark:text-zinc-400">No courses yet.</p>
        ) : (
          <ul className="space-y-2">
            {courses.map((c) => (
              <li key={c.id} className={`${rowClass} flex items-center justify-between gap-2`}>
                <Link to={`/courses/${c.id}`} className="flex-1 min-w-0 text-zinc-800 dark:text-zinc-200 hover:underline">
                  {c.name}
                </Link>
                <OverflowMenu items={[{ label: "Delete", onClick: () => deleteCourse(c), danger: true }]} />
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
