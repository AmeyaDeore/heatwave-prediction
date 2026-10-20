import { LockKeyhole } from "lucide-react";
import type { ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { useSession } from "@/state/session-context";

/**
 * Gate for write actions that need an authenticated official ("Issue Warning", "Save as
 * Draft"). Signed in: renders the action. Signed out: a button that opens sign-in instead, so
 * the action is visible but cannot fire. The API enforces this too; this is the UX half.
 */
export function ProtectedAction({
  children,
  label = "Sign in to continue",
}: {
  children: ReactNode;
  /** What the signed-out button says, e.g. "Sign in to issue". */
  label?: string;
}) {
  const { isAuthenticated, requestSignIn } = useSession();
  if (isAuthenticated) return <>{children}</>;
  return (
    <Button variant="outline" onClick={requestSignIn}>
      <LockKeyhole aria-hidden="true" />
      {label}
    </Button>
  );
}
