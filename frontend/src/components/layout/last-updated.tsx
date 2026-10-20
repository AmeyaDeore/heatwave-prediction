import { RefreshCw } from "lucide-react";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { formatDateTime, formatRelative, formatTime } from "@/lib/format";
import { useLastUpdated } from "@/lib/query/last-updated";
import { cn } from "@/lib/utils";

/** Re-render every 30 s so "2 min ago" keeps moving between fetches. */
function useNow(intervalMs = 30_000) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), intervalMs);
    return () => clearInterval(timer);
  }, [intervalMs]);
  return now;
}

/** The nav shell's "last updated" indicator plus a manual refresh of what's on screen. */
export function LastUpdated({ className }: { className?: string }) {
  const { updatedAt, fetching, refresh } = useLastUpdated();
  const now = useNow();

  return (
    <div className={cn("flex items-center gap-1 text-xs text-nav-muted", className)}>
      <span aria-live="polite" className="tabular whitespace-nowrap">
        {updatedAt ? (
          <>
            <span className="hidden xl:inline">Updated </span>
            <time dateTime={new Date(updatedAt).toISOString()} title={formatDateTime(updatedAt)}>
              {formatTime(updatedAt)}
            </time>
            <span className="hidden sm:inline"> · {formatRelative(updatedAt, now)}</span>
          </>
        ) : fetching ? (
          "Loading…"
        ) : (
          "Not loaded yet"
        )}
      </span>
      <Tooltip>
        <TooltipTrigger asChild>
          <Button
            variant="ghost"
            size="icon-sm"
            onClick={() => void refresh()}
            disabled={fetching}
            aria-label="Refresh data"
            className="text-nav-muted hover:bg-nav-accent hover:text-nav-foreground disabled:opacity-100"
          >
            <RefreshCw aria-hidden="true" className={cn(fetching && "animate-spin")} />
          </Button>
        </TooltipTrigger>
        <TooltipContent>Refresh data</TooltipContent>
      </Tooltip>
    </div>
  );
}
