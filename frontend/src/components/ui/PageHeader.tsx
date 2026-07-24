import type { ReactNode } from "react";

// Sticky page header shared by the redesigned pages: a truncating title, an
// optional subtitle line, and an optional cluster of right-aligned actions.
export function PageHeader({
  title,
  subtitle,
  right,
}: {
  title: ReactNode;
  subtitle?: ReactNode;
  right?: ReactNode;
}) {
  return (
    <header className="sticky top-0 z-20 bg-app-light/85 dark:bg-app-dark/85 backdrop-blur border-b border-zinc-200 dark:border-white/5">
      <div className="max-w-3xl mx-auto px-6 py-3 flex items-center justify-between gap-4">
        <div className="min-w-0">
          <h1 className="text-lg font-semibold text-zinc-900 dark:text-zinc-100 truncate">{title}</h1>
          {subtitle && <p className="text-xs text-zinc-400 dark:text-zinc-500">{subtitle}</p>}
        </div>
        {right && <div className="flex items-center gap-1 shrink-0">{right}</div>}
      </div>
    </header>
  );
}
