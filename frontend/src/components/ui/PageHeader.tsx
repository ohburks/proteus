import type { ReactNode } from "react";
import { Link, type To } from "react-router-dom";

// Sticky page header shared by the redesigned pages: a truncating title, an
// optional parent-page link, subtitle line, and cluster of right-aligned actions.
export function PageHeader({
  title,
  subtitle,
  backTo,
  backLabel = "Back",
  right,
}: {
  title: ReactNode;
  subtitle?: ReactNode;
  backTo?: To;
  backLabel?: string;
  right?: ReactNode;
}) {
  return (
    <header className="sticky top-0 z-20 bg-app-light/85 dark:bg-app-dark/85 backdrop-blur border-b border-zinc-200 dark:border-white/5">
      <div className="max-w-3xl mx-auto px-6 py-3 flex items-center justify-between gap-4">
        <div className="flex items-center gap-1.5 min-w-0">
          {backTo && (
            <Link
              to={backTo}
              aria-label={backLabel}
              title={backLabel}
              className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-lg text-zinc-500 dark:text-zinc-400 hover:bg-black/5 hover:text-zinc-900 dark:hover:bg-white/10 dark:hover:text-zinc-100"
            >
              ←
            </Link>
          )}
          <div className="min-w-0">
            <h1 className="text-lg font-semibold text-zinc-900 dark:text-zinc-100 truncate">{title}</h1>
            {subtitle && <p className="text-xs text-zinc-400 dark:text-zinc-500 truncate">{subtitle}</p>}
          </div>
        </div>
        {right && <div className="flex items-center gap-1 shrink-0">{right}</div>}
      </div>
    </header>
  );
}
