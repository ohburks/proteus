export interface TabDef<T extends string> {
  key: T;
  label: string;
}

// Underlined tab bar. Generic over the tab key so callers keep their own
// string-literal union (e.g. "ungraded" | "graded").
export function Tabs<T extends string>({
  tabs,
  active,
  onChange,
  className,
}: {
  tabs: TabDef<T>[];
  active: T;
  onChange: (key: T) => void;
  className?: string;
}) {
  return (
    <div className={`flex items-center gap-5 border-b border-zinc-200 dark:border-white/10 ${className ?? ""}`}>
      {tabs.map((t) => (
        <button
          key={t.key}
          onClick={() => onChange(t.key)}
          className={`px-1 pb-2.5 text-sm font-medium border-b-2 -mb-px transition-colors ${
            active === t.key
              ? "border-blue-500 text-zinc-900 dark:text-zinc-100"
              : "border-transparent text-zinc-500 dark:text-zinc-400 hover:text-zinc-800 dark:hover:text-zinc-200"
          }`}
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}
