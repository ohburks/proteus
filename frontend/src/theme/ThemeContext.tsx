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

  useEffect(() => {
    const root = document.documentElement;
    const next = resolve(preference);
    setResolved(next);
    root.classList.toggle("dark", next === "dark");
  }, [preference]);

  useEffect(() => {
    if (preference !== "system") return;
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const handler = () => setResolved(resolve("system"));
    mq.addEventListener("change", handler);
    return () => mq.removeEventListener("change", handler);
  }, [preference]);

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
