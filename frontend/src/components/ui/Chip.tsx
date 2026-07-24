import type { ReactNode } from "react";

// A toggle button that reveals/hides a panel (Add essay, Grading setup, Add
// excerpt, New assignment, …). `active` reflects whether its panel is open.
export function Chip({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium border transition-colors ${
        active
          ? "border-blue-500/50 bg-blue-500/10 text-blue-700 dark:text-blue-300"
          : "border-zinc-200 dark:border-white/10 text-zinc-600 dark:text-zinc-300 hover:bg-black/[0.03] dark:hover:bg-white/5"
      }`}
    >
      {children}
    </button>
  );
}
