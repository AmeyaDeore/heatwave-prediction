/**
 * Sign-in screen (Part 15 §6, Part 10 R2.1; the teacher's mandatory "user login", M1). Every
 * page needs a session since Revision 2: the route guard sends signed-out visits here with
 * `?next=` and this page sends the official back after signing in.
 */
import { CloudSun, LoaderCircle } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Navigate, useNavigate, useSearchParams } from "react-router";
import { PRODUCT_NAME, safeNext } from "@/app/navigation";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { describeError, isApiError } from "@/lib/api/errors";
import { useSession } from "@/state/session-context";

const NOTICE = {
  expired: "Your session expired. Sign in again to continue.",
  signed_out: "You have signed out.",
} as const;

export function LoginPage() {
  const { isAuthenticated, signIn, endedReason } = useSession();
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const next = safeNext(params.get("next"));
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<unknown>(null);

  if (isAuthenticated && !submitting) return <Navigate to={next} replace />;

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await signIn(username.trim(), password);
      navigate(next, { replace: true });
    } catch (caught) {
      setError(caught);
      setPassword("");
      setSubmitting(false);
    }
  }

  // The API gives one message for a wrong password and an unknown user (docs/api §2); so do we.
  const failure = !error
    ? null
    : isApiError(error) && error.status === 401
      ? "Incorrect username or password."
      : isApiError(error) && error.status === 429
        ? `Too many sign-in attempts. Try again in ${error.retryAfter ?? 60} seconds.`
        : describeError(error).description;

  return (
    <main className="grid min-h-svh place-items-center bg-background px-4 py-10">
      <div className="flex w-full max-w-sm flex-col gap-6">
        <div className="flex flex-col items-center gap-3 text-center">
          <span className="grid size-12 place-items-center rounded-xl bg-gradient-to-br from-tone-warning to-tone-danger text-tone-danger-fg shadow-sm">
            <CloudSun aria-hidden="true" className="size-6" strokeWidth={2.25} />
          </span>
          <div className="flex flex-col gap-1">
            <h1 className="text-xl font-semibold tracking-tight">{PRODUCT_NAME}</h1>
            <p className="text-sm text-muted-foreground">
              Heatwave early warning for disaster management officials, Maharashtra
            </p>
          </div>
        </div>

        <section
          aria-labelledby="sign-in-title"
          className="flex flex-col gap-5 rounded-xl border bg-card p-6 text-card-foreground shadow-xs"
        >
          <div className="flex flex-col gap-1">
            <h2 id="sign-in-title" className="text-base font-semibold">
              Sign in
            </h2>
            <p className="text-sm text-muted-foreground">Use the account your office issued.</p>
          </div>
          {endedReason && !error && (
            <Alert role="status">
              <AlertDescription>{NOTICE[endedReason]}</AlertDescription>
            </Alert>
          )}
          <form onSubmit={onSubmit} className="flex flex-col gap-4" noValidate>
            <div className="flex flex-col gap-2">
              <Label htmlFor="login-username">Username</Label>
              <Input
                id="login-username"
                autoComplete="username"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                required
                autoFocus
              />
            </div>
            <div className="flex flex-col gap-2">
              <Label htmlFor="login-password">Password</Label>
              <Input
                id="login-password"
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
            <Button type="submit" disabled={submitting || !username.trim() || !password}>
              {submitting && <LoaderCircle aria-hidden="true" className="animate-spin" />}
              {submitting ? "Signing in…" : "Sign in"}
            </Button>
          </form>
        </section>
        <p className="text-center text-xs text-muted-foreground">
          No self-registration: accounts are issued by your office.
        </p>
      </div>
    </main>
  );
}
