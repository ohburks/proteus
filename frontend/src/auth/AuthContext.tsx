import { createContext, useContext, useState, type ReactNode } from "react";
import { api, getToken, setToken } from "../lib/api";
import type { LoginResponse } from "../lib/types";

interface AuthState {
  token: string | null;
  role: "admin" | "instructor" | null;
  instructorId: string | null;
  themePreference: "system" | "light" | "dark";
  login: (username: string, password: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setTok] = useState<string | null>(getToken());
  const [role, setRole] = useState<"admin" | "instructor" | null>(
    (localStorage.getItem("drg_role") as "admin" | "instructor" | null) ?? null,
  );
  const [instructorId, setInstructorId] = useState<string | null>(localStorage.getItem("drg_instructor_id"));
  const [themePreference, setThemePreference] = useState<"system" | "light" | "dark">(
    (localStorage.getItem("drg_theme") as "system" | "light" | "dark" | null) ?? "system",
  );

  async function login(username: string, password: string) {
    const res = await api.post<LoginResponse>("/api/auth/login", { username, password });
    setToken(res.token);
    setTok(res.token);
    setRole(res.role);
    setInstructorId(res.instructor_id);
    setThemePreference(res.theme_preference);
    localStorage.setItem("drg_role", res.role);
    if (res.instructor_id) localStorage.setItem("drg_instructor_id", res.instructor_id);
    localStorage.setItem("drg_theme", res.theme_preference);
    // Let ThemeProvider adopt the account's saved theme without a page reload.
    window.dispatchEvent(new Event("drg-theme-changed"));
  }

  function logout() {
    setToken(null);
    setTok(null);
    setRole(null);
    setInstructorId(null);
    localStorage.removeItem("drg_role");
    localStorage.removeItem("drg_instructor_id");
    // Clear the theme too, so the next account doesn't inherit this user's.
    localStorage.removeItem("drg_theme");
  }

  return (
    <AuthContext.Provider value={{ token, role, instructorId, themePreference, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
