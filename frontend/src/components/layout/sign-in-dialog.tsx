import { LoaderCircle, LockKeyhole } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { describeError, isApiError } from "@/lib/api/errors";
import { useSession } from "@/state/session-context";

/**
 * Sign-in for protected actions (issuing alerts). Opened from the nav or by any protected
 * action via `requestSignIn()`. Part 15 may replace it with a full login page; the session
 * contract stays the same.
 */
export function SignInDialog() {
  const { signInOpen, setSignInOpen, signIn, endedReason } = useSession();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<unknown>(null);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await signIn(username.trim(), password);
      setPassword("");
      setSignInOpen(false);
    } catch (caught) {
      setError(caught);
    } finally {
      setSubmitting(false);
    }
  }

  // The API gives one message for a wrong password and an unknown user (docs/api §2); so do we.
  const failure = !error
    ? null
    : isApiError(error) && error.status === 401
      ? "Incorrect username or password."
      : describeError(error).description;
  return (
    <Dialog
      open={signInOpen}
      onOpenChange={(open) => {
        setSignInOpen(open);
        if (!open) setError(null);
      }}
    >
      <DialogContent className="sm:max-w-sm">
        <DialogHeader>
          <div className="mb-1 grid size-10 place-items-center rounded-full bg-muted">
            <LockKeyhole aria-hidden="true" className="size-5 text-muted-foreground" />
          </div>
          <DialogTitle>Sign in</DialogTitle>
          <DialogDescription>
            {endedReason === "expired"
              ? "Your session expired. Sign in again to continue."
              : "Issuing and editing alerts requires an authorised official."}
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={onSubmit} className="flex flex-col gap-4" noValidate>
          <div className="flex flex-col gap-2">
            <Label htmlFor="sign-in-username">Username</Label>
            <Input
              id="sign-in-username"
              autoComplete="username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              required
              autoFocus
            />
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor="sign-in-password">Password</Label>
            <Input
              id="sign-in-password"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          </div>
          {failure && (
            <Alert variant="destructive" role="alert">
              <AlertDescription>{failure}</AlertDescription>
            </Alert>
          )}
          <DialogFooter>
            <Button
              type="submit"
              disabled={submitting || !username.trim() || !password}
              className="w-full"
            >
              {submitting && <LoaderCircle aria-hidden="true" className="animate-spin" />}
              {submitting ? "Signing in…" : "Sign in"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
