import { useState } from "react";

export type MenuItem = { label: string; onClick: () => void; danger?: boolean; disabled?: boolean };

// Collapses a row's secondary/destructive actions behind a single "⋯" so each
// row leads with one primary action. A full-screen transparent backdrop closes
// it on any outside click.
export function OverflowMenu({ items }: { items: MenuItem[] }) {
  const [open, setOpen] = useState(false);
  if (items.length === 0) return null;
  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-label="More actions"
        className="px-2 py-1.5 rounded-lg text-zinc-500 dark:text-zinc-400 hover:bg-black/5 dark:hover:bg-white/10 leading-none"
      >
        ⋯
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-30" onClick={() => setOpen(false)} />
          <div className="absolute right-0 top-full mt-1 z-40 min-w-[11rem] overflow-hidden rounded-xl border border-zinc-200 dark:border-white/10 bg-white dark:bg-surface-dark shadow-lg py-1">
            {items.map((it, i) => (
              <button
                key={i}
                type="button"
                disabled={it.disabled}
                onClick={() => {
                  setOpen(false);
                  it.onClick();
                }}
                className={`block w-full px-3 py-1.5 text-left text-xs font-medium disabled:opacity-40 ${
                  it.danger
                    ? "text-red-600 dark:text-red-400 hover:bg-red-500/10"
                    : "text-zinc-700 dark:text-zinc-300 hover:bg-black/[0.04] dark:hover:bg-white/5"
                }`}
              >
                {it.label}
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
