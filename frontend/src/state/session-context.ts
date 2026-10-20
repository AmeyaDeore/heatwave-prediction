import { createContext, useContext } from "react";
import type { UserOut } from "@/lib/api/types";

export interface StoredSession {
  token: string;
  expiresAt: string;
  user: UserOut;
}

export type SessionEndReason = "signed_out" | "expired";

export interface SessionContextValue {
  user: UserOut | null;
  token: string | null;
  isAuthenticated: boolean;
  /** Why the last session ended, so the sign-in dialog can say "your session expired". */
  endedReason: SessionEndReason | null;
  signIn: (username: string, password: string) => Promise<UserOut>;
  signOut: (reason?: SessionEndReason) => void;
  signInOpen: boolean;
  setSignInOpen: (open: boolean) => void;
  /** Open the sign-in dialog (e.g. a signed-out user pressed "Issue Warning"). */
  requestSignIn: () => void;
  /**
   * Run a protected request with the current token. With no session, or on a 401, it ends the
   * session, opens sign-in and rejects with the 401 so the caller's error state still shows.
   */
  withToken: <T>(call: (token: string) => Promise<T>) => Promise<T>;
}

export const SessionContext = createContext<SessionContextValue | null>(null);

export function useSession(): SessionContextValue {
  const context = useContext(SessionContext);
  if (!context) throw new Error("useSession must be used inside <SessionProvider>.");
  return context;
}
