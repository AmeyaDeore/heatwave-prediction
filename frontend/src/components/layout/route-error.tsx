import { LoaderCircle, TriangleAlert } from "lucide-react";
import { useRouteError } from "react-router";
import { Button } from "@/components/ui/button";

/** Last-resort boundary for a render crash: plain words and a reload, never a stack trace. */
export function RouteErrorBoundary() {
  const error = useRouteError();
  if (import.meta.env.DEV) console.error(error);
  return (
    <div role="alert" className="grid min-h-svh place-items-center bg-background p-6">
      <div className="flex max-w-md flex-col items-center gap-4 text-center">
        <span className="grid size-12 place-items-center rounded-full bg-tone-danger-subtle text-tone-danger-subtle-fg">
          <TriangleAlert aria-hidden="true" className="size-6" />
        </span>
        <h1 className="text-xl font-semibold">This page stopped working</h1>
        <p className="text-sm text-muted-foreground">
          Something unexpected happened while showing this page. Reloading usually fixes it.
        </p>
        <Button onClick={() => window.location.reload()}>Reload</Button>
      </div>
    </div>
  );
}

/** First paint while the initial page chunk loads. */
export function RouteLoading() {
  return (
    <div role="status" className="grid min-h-svh place-items-center bg-background">
      <LoaderCircle aria-hidden="true" className="size-6 animate-spin text-muted-foreground" />
      <span className="sr-only">Loading…</span>
    </div>
  );
}
