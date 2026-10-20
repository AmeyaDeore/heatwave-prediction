/**
 * Light / dark / system theme. index.html applies the stored choice before first paint (no
 * flash); this provider keeps <html class="dark"> in sync afterwards.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { readStored, STORAGE_KEYS, writeStored } from "@/lib/storage";
import { ThemeContext, type ThemePreference } from "./theme-context";

const DARK_QUERY = "(prefers-color-scheme: dark)";

function parsePreference(raw: unknown): ThemePreference | null {
  return raw === "light" || raw === "dark" || raw === "system" ? raw : null;
}

function systemPrefersDark(): boolean {
  return typeof window.matchMedia === "function" && window.matchMedia(DARK_QUERY).matches;
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [preference, setPreferenceState] = useState<ThemePreference>(
    () => readStored("local", STORAGE_KEYS.theme, parsePreference) ?? "system",
  );
  const [systemDark, setSystemDark] = useState(systemPrefersDark);

  useEffect(() => {
    if (typeof window.matchMedia !== "function") return;
    const media = window.matchMedia(DARK_QUERY);
    const onChange = () => setSystemDark(media.matches);
    media.addEventListener("change", onChange);
    return () => media.removeEventListener("change", onChange);
  }, []);

  const resolved = preference === "system" ? (systemDark ? "dark" : "light") : preference;

  useEffect(() => {
    document.documentElement.classList.toggle("dark", resolved === "dark");
  }, [resolved]);

  const setPreference = useCallback((next: ThemePreference) => {
    setPreferenceState(next);
    writeStored("local", STORAGE_KEYS.theme, next);
  }, []);

  const value = useMemo(
    () => ({ preference, resolved, setPreference }),
    [preference, resolved, setPreference],
  );
  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}
