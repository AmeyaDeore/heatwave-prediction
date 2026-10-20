/**
 * One error type for every failed request, and the one place that turns it into words an
 * official can act on (§6: "a clear, non-technical message plus a retry action").
 */
import type { ErrorKind } from "./types";

/** API kinds plus the two failures that never reach the API. */
export type ApiFailureKind = ErrorKind | "network" | "timeout";

export class ApiError extends Error {
  readonly kind: ApiFailureKind;
  readonly code: string;
  readonly status: number;
  readonly requestId: string | null;
  readonly details: unknown;
  /** Seconds, from Retry-After on a 429. */
  readonly retryAfter: number | null;

  constructor(init: {
    kind: ApiFailureKind;
    code: string;
    message: string;
    status: number;
    requestId?: string | null;
    details?: unknown;
    retryAfter?: number | null;
  }) {
    super(init.message);
    this.name = "ApiError";
    this.kind = init.kind;
    this.code = init.code;
    this.status = init.status;
    this.requestId = init.requestId ?? null;
    this.details = init.details ?? null;
    this.retryAfter = init.retryAfter ?? null;
  }

  /** Worth retrying automatically: the request was fine, something on the way failed. */
  get isTransient(): boolean {
    return (
      this.kind === "network" ||
      this.kind === "timeout" ||
      this.kind === "upstream" ||
      this.status === 429 ||
      this.status >= 500
    );
  }
}

export function isApiError(error: unknown): error is ApiError {
  return error instanceof ApiError;
}

export interface ErrorDescription {
  title: string;
  description: string;
  /** Show a Retry action. False when retrying the same request cannot help. */
  retryable: boolean;
  /** Quote this in a bug report: it finds the backend log line (docs/api §1). */
  reference: string | null;
}

/**
 * Plain-language wording for each failure. The API's own `message` is already written for the
 * user (docs/api §1), so client errors show it; the rest get fixed wording rather than codes.
 */
export function describeError(error: unknown): ErrorDescription {
  if (!isApiError(error)) {
    return {
      title: "Something went wrong",
      description: "The page hit an unexpected problem. Try again, and reload if it persists.",
      retryable: true,
      reference: null,
    };
  }
  const reference = error.requestId;
  switch (error.kind) {
    case "network":
      return {
        title: "Can't reach the server",
        description:
          "Check your connection. The data will load again once the service is reachable.",
        retryable: true,
        reference,
      };
    case "timeout":
      return {
        title: "The server is taking too long",
        description: "The request timed out. Try again in a moment.",
        retryable: true,
        reference,
      };
    case "upstream":
      return {
        title: "Weather data is unavailable",
        description:
          "The latest weather data could not be read, so this can't be calculated right now.",
        retryable: true,
        reference,
      };
    case "internal":
      return {
        title: "The service had a problem",
        description: "This is on our side, not yours. Try again; if it keeps happening, report it.",
        retryable: true,
        reference,
      };
    case "client":
      if (error.status === 401) {
        return {
          title: "Please sign in",
          description: "Your session has ended. Sign in again to continue.",
          retryable: false,
          reference,
        };
      }
      if (error.status === 429) {
        const wait = error.retryAfter ? ` Try again in ${error.retryAfter} s.` : "";
        return {
          title: "Too many requests",
          description: `Slow down for a moment.${wait}`,
          retryable: true,
          reference,
        };
      }
      if (error.status === 404) {
        return {
          title: "Nothing here yet",
          description: error.message,
          retryable: false,
          reference,
        };
      }
      return {
        title: "Request not accepted",
        description: error.message,
        retryable: false,
        reference,
      };
  }
}
