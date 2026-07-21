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
    if (!name.trim()) return;
    setError(null);
    try {
      await api.post("/api/courses", { name });
      setName("");
      refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to create course");
    }
  }

  return (
    <div className="max-w-3xl mx-auto px-6 py-8 bg-gray-50 dark:bg-gray-950 min-h-[calc(100vh-3.5rem)]">
      <h1 className="text-xl font-semibold text-gray-900 dark:text-gray-100 mb-6">Courses</h1>

      {role === "admin" ? (
        <p className="text-sm text-amber-700 dark:text-amber-400 bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 rounded-lg px-4 py-3 mb-6">
          The admin role is for setup and oversight across instructors — it isn't tied to an
          instructor identity, so it can't own courses directly. Log in as{" "}
          <code className="font-mono">instructor</code>/<code className="font-mono">instruct123</code>{" "}
          to create and manage courses.
        </p>
      ) : (
        <form onSubmit={createCourse} className="flex gap-2 mb-2">
          <input
            className="flex-1 px-3 py-2 border border-gray-300 dark:border-gray-700 rounded bg-white dark:bg-gray-900 text-gray-900 dark:text-gray-100"
            placeholder="New course name"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
          <button className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 dark:bg-indigo-500 dark:hover:bg-indigo-400 text-white rounded text-sm font-medium">
            Add course
          </button>
        </form>
      )}
      {error && <p className="text-sm text-red-600 dark:text-red-400 mb-4">{error}</p>}

      {loading ? (
        <p className="text-gray-500 dark:text-gray-400">Loading…</p>
      ) : courses.length === 0 ? (
        <p className="text-gray-500 dark:text-gray-400">No courses yet.</p>
      ) : (
        <ul className="divide-y divide-gray-200 dark:divide-gray-800 bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-lg overflow-hidden">
          {courses.map((c) => (
            <li key={c.id}>
              <Link
                to={`/courses/${c.id}`}
                className="block px-4 py-3 text-gray-800 dark:text-gray-200 hover:bg-gray-50 dark:hover:bg-gray-800"
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
