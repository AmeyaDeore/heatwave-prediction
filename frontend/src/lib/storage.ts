/**
 * Guarded Web Storage access. Storage can throw (private mode, blocked site data) or hold junk
 * from an older build; neither may break the app, so every read falls back to a default.
 */
type Area = "local" | "session";

function area(kind: Area): Storage | null {
  try {
    return kind === "local" ? window.localStorage : window.sessionStorage;
  } catch {
    return null;
  }
}

export function readStored<T>(
  kind: Area,
  key: string,
  parse: (raw: unknown) => T | null,
): T | null {
  try {
    const raw = area(kind)?.getItem(key);
    return raw === null || raw === undefined ? null : parse(JSON.parse(raw));
  } catch {
    return null;
  }
}

export function writeStored(kind: Area, key: string, value: unknown): void {
  try {
    if (value === null || value === undefined) area(kind)?.removeItem(key);
    else area(kind)?.setItem(key, JSON.stringify(value));
  } catch {
    // Persistence is a convenience; the in-memory state is still correct.
  }
}

export const STORAGE_KEYS = {
  region: "hw.region",
  theme: "hw.theme",
  session: "hw.session",
} as const;
