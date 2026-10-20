/**
 * Authenticated session (Part 10 §3): global, populated by sign-in, read by the nav shell (to
 * show/hide protected actions) and by any write action (issuing an alert).
 *
 * The bearer token is kept in sessionStorage so it ends with the tab, and is dropped at its
 * `expires_at` or on the first 401. Part 15 owns the full login flow, roles and region scoping;
 * this provider is the seam it extends.
 */
import { useCallback, useEffect, useLayoutEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { setSessionBridge } from "@/lib/api/client";
import { api } from "@/lib/api/endpoints";
import { ApiError, isApiError } from "@/lib/api/errors";
import { readStored, STORAGE_KEYS, writeStored } from "@/lib/storage";
import {
  SessionContext,
  type SessionContextValue,
  type SessionEndReason,
  type StoredSession,
} from "./session-context";

function parseStored(raw: unknown): StoredSession | null {
  if (!raw || typeof raw !== "object") return null;
  const s = raw as Partial<StoredSession>;
  if (typeof s.token !== "string" || typeof s.expiresAt !== "string" || !s.user) return null;
  return Date.parse(s.expiresAt) > Date.now() ? (s as StoredSession) : null;
}

const UNAUTHENTICATED = new ApiError({
  kind: "client",
  code: "UNAUTHORIZED",
  message: "Sign in to continue.",
  status: 401,
});

export function SessionProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<StoredSession | null>(() =>
    readStored("session", STORAGE_KEYS.session, parseStored),
  );
  const [endedReason, setEndedReason] = useState<SessionEndReason | null>(null);
  const [signInOpen, setSignInOpen] = useState(false);

  const signOut = useCallback((reason: SessionEndReason = "signed_out") => {
    setSession(null);
    setEndedReason(reason);
    writeStored("session", STORAGE_KEYS.session, null);
  }, []);

  // End the session exactly at expires_at rather than on the next failed request.
  useEffect(() => {
    if (!session) return;
    const remaining = Date.parse(session.expiresAt) - Date.now();
    const timer = setTimeout(() => signOut("expired"), Math.max(0, remaining));
    return () => clearTimeout(timer);
  }, [session, signOut]);

  const signIn = useCallback(async (username: string, password: string) => {
    const result = await api.login({ username, password });
    const next: StoredSession = {
      token: result.access_token,
      expiresAt: result.expires_at,
      user: result.user,
    };
    setSession(next);
    setEndedReason(null);
    writeStored("session", STORAGE_KEYS.session, next);
    return result.user;
  }, []);

  const requestSignIn = useCallback(() => setSignInOpen(true), []);

  const token = session?.token ?? null;

  // Every API call carries the session's token, and a 401 on one ends the session (Revision 2:
  // every data endpoint needs a session). A layout effect runs before any child's passive
  // effects, so the very first queries already carry the token.
  useLayoutEffect(() => {
    setSessionBridge({ token: () => token, onUnauthorized: () => signOut("expired") });
    return () => setSessionBridge(null);
  }, [token, signOut]);
  const withToken = useCallback(
    async <T,>(call: (token: string) => Promise<T>): Promise<T> => {
      if (!token) {
        setSignInOpen(true);
        throw UNAUTHENTICATED;
      }
      try {
        return await call(token);
      } catch (error) {
        if (isApiError(error) && error.status === 401) {
          signOut("expired");
          setSignInOpen(true);
        }
        throw error;
      }
    },
    [token, signOut],
  );

  const value = useMemo<SessionContextValue>(
    () => ({
      user: session?.user ?? null,
      token,
      isAuthenticated: session !== null,
      endedReason,
      signIn,
      signOut,
      signInOpen,
      setSignInOpen,
      requestSignIn,
      withToken,
    }),
    [session, token, endedReason, signIn, signOut, signInOpen, requestSignIn, withToken],
  );

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}
