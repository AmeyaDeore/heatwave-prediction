/**
 * Loading, error and empty states (Part 10 §6), defined once. Every data-driven card renders
 * one of these through <QueryState>, never a blank card or a raw error.
 */
import type { UseQueryResult } from "@tanstack/react-query";
import { CloudOff, Inbox, RotateCw, TriangleAlert, type LucideIcon } from "lucide-react";
import type { ReactNode } from "react";
import { Button } from "@/components/ui/button";
import {
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@/components/ui/empty";
import { Skeleton } from "@/components/ui/skeleton";
import { describeError, isApiError } from "@/lib/api/errors";
import { cn } from "@/lib/utils";

// --- Loading -------------------------------------------------------------------------------

export type LoadingShape = "lines" | "metric" | "list" | "chart" | "factors";

/** A placeholder shaped like the content it stands in for, so the layout doesn't jump. */
export function LoadingState({
  shape = "lines",
  rows = 3,
  label = "Loading",
  className,
}: {
  shape?: LoadingShape;
  rows?: number;
  label?: string;
  className?: string;
}) {
  return (
    <div
      role="status"
      aria-live="polite"
      data-slot="loading-state"
      className={cn("flex flex-col gap-3", className)}
    >
      <span className="sr-only">{label}…</span>
      {shape === "metric" && (
        <>
          <Skeleton className="h-9 w-28" />
          <Skeleton className="h-4 w-40" />
        </>
      )}
      {shape === "chart" && <Skeleton className="h-56 w-full" />}
      {shape === "lines" &&
        Array.from({ length: rows }, (_, i) => (
          <Skeleton key={i} className={cn("h-4", i === rows - 1 ? "w-3/5" : "w-full")} />
        ))}
      {shape === "list" &&
        Array.from({ length: rows }, (_, i) => <Skeleton key={i} className="h-11 w-full" />)}
      {shape === "factors" &&
        Array.from({ length: rows }, (_, i) => (
          <div key={i} className="flex flex-col gap-2">
            <div className="flex justify-between">
              <Skeleton className="h-4 w-40" />
              <Skeleton className="h-4 w-16" />
            </div>
            <Skeleton className="h-2 w-full" />
          </div>
        ))}
    </div>
  );
}

// --- Error ---------------------------------------------------------------------------------

export function ErrorState({
  error,
  onRetry,
  retrying = false,
  compact = false,
  className,
}: {
  error: unknown;
  onRetry?: () => void;
  retrying?: boolean;
  /** One-line form for small cards (metric cards, the nav). */
  compact?: boolean;
  className?: string;
}) {
  const { title, description, retryable, reference } = describeError(error);
  const Icon = isApiError(error) && error.kind === "network" ? CloudOff : TriangleAlert;
  const retry = retryable && onRetry && (
    <Button variant="outline" size={compact ? "xs" : "sm"} onClick={onRetry} disabled={retrying}>
      <RotateCw aria-hidden="true" className={cn(retrying && "animate-spin")} />
      {retrying ? "Retrying…" : "Try again"}
    </Button>
  );

  if (compact) {
    return (
      <div
        role="alert"
        data-slot="error-state"
        className={cn("flex flex-wrap items-center gap-2 text-sm", className)}
      >
        <Icon aria-hidden="true" className="size-4 shrink-0 text-tone-danger-subtle-fg" />
        <span className="font-medium">{title}</span>
        {retry}
      </div>
    );
  }
  return (
    <Empty role="alert" data-slot="error-state" className={cn("gap-4 p-6 md:p-8", className)}>
      <EmptyHeader>
        <EmptyMedia variant="icon" className="bg-tone-danger-subtle text-tone-danger-subtle-fg">
          <Icon aria-hidden="true" />
        </EmptyMedia>
        <EmptyTitle>{title}</EmptyTitle>
        <EmptyDescription>{description}</EmptyDescription>
      </EmptyHeader>
      {(retry || reference) && (
        <EmptyContent>
          {retry}
          {reference && (
            <p className="text-xs text-muted-foreground">
              Reference <code className="font-mono">{reference}</code>
            </p>
          )}
        </EmptyContent>
      )}
    </Empty>
  );
}

// --- Empty ---------------------------------------------------------------------------------

export function EmptyState({
  title,
  description,
  icon: Icon = Inbox,
  action,
  className,
}: {
  title: string;
  description?: ReactNode;
  icon?: LucideIcon;
  /** The next step, e.g. "Create alert" or "Run a prediction". */
  action?: ReactNode;
  className?: string;
}) {
  return (
    <Empty data-slot="empty-state" className={cn("gap-4 p-6 md:p-8", className)}>
      <EmptyHeader>
        <EmptyMedia variant="icon">
          <Icon aria-hidden="true" />
        </EmptyMedia>
        <EmptyTitle>{title}</EmptyTitle>
        {description && <EmptyDescription>{description}</EmptyDescription>}
      </EmptyHeader>
      {action && <EmptyContent>{action}</EmptyContent>}
    </Empty>
  );
}

// --- One convention for any query -----------------------------------------------------------

export interface QueryStateProps<T> {
  query: Pick<
    UseQueryResult<T>,
    "data" | "error" | "isPending" | "isError" | "isFetching" | "refetch"
  >;
  children: (data: T) => ReactNode;
  loading?: ReactNode;
  /** When the data counts as empty (e.g. no alerts). */
  isEmpty?: (data: T) => boolean;
  empty?: ReactNode;
  /** Treat 404 NOT_FOUND as empty, e.g. "no prediction made yet for this region". */
  notFoundAsEmpty?: boolean;
  compactError?: boolean;
}

/**
 * The default for every data-driven card (§6): skeleton while loading, a plain-language error
 * with Retry when it fails, an empty state when there is nothing, otherwise the content.
 * If a background refetch fails while data is on screen, the data stays (stale but visible,
 * Part 11 §4) and the nav's "last updated" time shows its age.
 */
export function QueryState<T>({
  query,
  children,
  loading = <LoadingState />,
  isEmpty,
  empty = <EmptyState title="No data yet" />,
  notFoundAsEmpty = false,
  compactError = false,
}: QueryStateProps<T>) {
  if (query.data !== undefined) {
    return isEmpty?.(query.data) ? empty : children(query.data);
  }
  if (query.isPending && !query.isError) return loading;
  if (notFoundAsEmpty && isApiError(query.error) && query.error.status === 404) return empty;
  return (
    <ErrorState
      error={query.error}
      onRetry={() => void query.refetch()}
      retrying={query.isFetching}
      compact={compactError}
    />
  );
}
