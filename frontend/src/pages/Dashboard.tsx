import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { api, ApiError } from "../lib/api";
import type { Course } from "../lib/types";

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

  return (
    <div className="max-w-3xl mx-auto px-6 py-8 bg-app-light dark:bg-app-dark min-h-[calc(100vh-3.5rem)]">
      <h1 className="text-xl font-semibold text-zinc-900 dark:text-zinc-100 mb-6">Courses</h1>

      {role === "admin" ? (
        <p className="text-sm text-amber-700 dark:text-amber-400 bg-amber-500/10 border border-amber-500/20 rounded-2xl px-4 py-3 mb-6">
          The admin role is for setup and oversight across instructors — it isn't tied to an
          instructor identity, so it can't own courses directly. Log in as{" "}
          <code className="font-mono">instructor</code>/<code className="font-mono">instruct123</code>{" "}
          to create and manage courses.
        </p>
      ) : (
        <form onSubmit={createCourse} className="flex gap-2 mb-2">
          <input
            className="flex-1 px-3 py-2 border border-zinc-300 dark:border-white/10 rounded-lg bg-white dark:bg-surface-dark text-zinc-900 dark:text-zinc-100"
            placeholder="New course name"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
          <button className="px-4 py-2 bg-blue-600 hover:bg-blue-500 dark:bg-blue-500 dark:hover:bg-blue-400 text-white rounded-lg text-sm font-medium">
            Add course
          </button>
        </form>
      )}
      {error && <p className="text-sm text-red-600 dark:text-red-400 mb-4">{error}</p>}

      {loading ? (
        <p className="text-zinc-500 dark:text-zinc-400">Loading…</p>
      ) : courses.length === 0 ? (
        <p className="text-zinc-500 dark:text-zinc-400">No courses yet.</p>
      ) : (
        <ul className="divide-y divide-zinc-200 dark:divide-white/5 bg-surface-light dark:bg-surface-dark border border-zinc-200 dark:border-transparent rounded-2xl overflow-hidden">
          {courses.map((c) => (
            <li key={c.id}>
              <Link
                to={`/courses/${c.id}`}
                className="block px-4 py-3 text-zinc-800 dark:text-zinc-200 hover:bg-black/[0.03] dark:hover:bg-white/5"
              >
                {c.name}
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
