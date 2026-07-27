import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { api, getToken } from "../lib/api";

type ThemePreference = "system" | "light" | "dark";

interface ThemeState {
  preference: ThemePreference;
  resolved: "light" | "dark";
  setPreference: (p: ThemePreference) => void;
}

const ThemeContext = createContext<ThemeState | null>(null);

function resolve(pref: ThemePreference): "light" | "dark" {
  if (pref === "system") {
    return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }
  return pref;
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [preference, setPref] = useState<ThemePreference>(
    (localStorage.getItem("drg_theme") as ThemePreference | null) ?? "system",
  );
  const [resolved, setResolved] = useState<"light" | "dark">(resolve(preference));

  // Keep `resolved` in sync with the chosen preference.
  useEffect(() => {
    setResolved(resolve(preference));
  }, [preference]);

  // Follow OS changes while on "system". Updating `resolved` here is what makes
  // the app re-theme live — the class toggle below is keyed on `resolved`, not
  // `preference`, so it reacts even though `preference` hasn't changed.
  useEffect(() => {
    if (preference !== "system") return;
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const handler = () => setResolved(resolve("system"));
    mq.addEventListener("change", handler);
    return () => mq.removeEventListener("change", handler);
  }, [preference]);

  // Apply the resolved theme to <html> whenever it changes (from a preference
  // change OR a live OS change).
  useEffect(() => {
    document.documentElement.classList.toggle("dark", resolved === "dark");
  }, [resolved]);

  // Login stores the server's saved theme in localStorage and dispatches this
  // event; adopt it so the preference reflects the account without a reload.
  useEffect(() => {
    const handler = () => {
      const stored = localStorage.getItem("drg_theme") as ThemePreference | null;
      if (stored) setPref(stored);
    };
    window.addEventListener("drg-theme-changed", handler);
    return () => window.removeEventListener("drg-theme-changed", handler);
  }, []);

  function setPreference(p: ThemePreference) {
    setPref(p);
    localStorage.setItem("drg_theme", p);
    if (getToken()) {
      api.put("/api/settings/theme", { theme_preference: p }).catch(() => {});
    }
  }

  return (
    <ThemeContext.Provider value={{ preference, resolved, setPreference }}>{children}</ThemeContext.Provider>
  );
}

export function useTheme(): ThemeState {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error("useTheme must be used within ThemeProvider");
  return ctx;
}
