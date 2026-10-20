import type { ReactNode } from "react";
import { Navigate, useLocation } from "react-router";
import { useSession } from "@/state/session-context";

/**
 * Route guard (Part 10 R2.1): every page needs a signed-in official. A signed-out visit, an
 * expired session or a 401 lands on /login, which returns here afterwards (`?next=`).
 * This is the UX half; the API enforces the same rule on every data endpoint.
 */
export function RequireSession({ children }: { children: ReactNode }) {
  const { isAuthenticated } = useSession();
  const location = useLocation();
  if (!isAuthenticated) {
    const next = `${location.pathname}${location.search}`;
    return <Navigate to={`/login?next=${encodeURIComponent(next)}`} replace />;
  }
  return <>{children}</>;
}
