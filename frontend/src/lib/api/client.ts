/**
 * The shared HTTP client (Part 10 §3). Every call to the backend goes through `apiRequest`:
 * base URL from env, the response envelope unwrapped once, every failure turned into one
 * ApiError, a timeout on every request, and the session's bearer token on every call.
 *
 * Revision 2 (Part 15 R2): every data endpoint needs a session, so the token comes from the
 * session bridge below unless a call passes its own. A 401 on a call that carried the
 * session's token ends the session (the route guard then returns to /login).
 *
 * Pages do not call this directly: they use the query hooks in src/lib/query/hooks.ts.
 */
import { env } from "@/lib/env";
import { ApiError } from "./errors";
import type { Envelope } from "./types";

export const DEFAULT_TIMEOUT_MS = 15_000;

type QueryValue = string | number | boolean | null | undefined;

export interface RequestOptions {
  method?: "GET" | "POST" | "PATCH";
  query?: Record<string, QueryValue>;
  body?: unknown;
  /** Bearer token; defaults to the current session's (see setSessionBridge). */
  token?: string | null;
  /** false: never attach the session token, and a 401 is not "session ended" (login). */
  auth?: boolean;
  signal?: AbortSignal;
  timeoutMs?: number;
}

/** Set by SessionProvider: where the token comes from, and what a 401 means. */
export interface SessionBridge {
  token: () => string | null;
  onUnauthorized: () => void;
}

let bridge: SessionBridge | null = null;

export function setSessionBridge(next: SessionBridge | null): void {
  bridge = next;
}

export function buildUrl(path: string, query?: Record<string, QueryValue>): string {
  const url = new URL(`${env.apiBaseUrl}${path.startsWith("/") ? path : `/${path}`}`);
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value !== undefined && value !== null && value !== "")
      url.searchParams.set(key, String(value));
  }
  return url.toString();
}

function parseRetryAfter(header: string | null): number | null {
  if (!header) return null;
  const seconds = Number(header);
  return Number.isFinite(seconds) && seconds >= 0 ? seconds : null;
}

export async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = "GET", query, body, signal, timeoutMs = DEFAULT_TIMEOUT_MS } = options;
  const useSession = options.auth !== false;
  const sessionToken = useSession && options.token === undefined ? (bridge?.token() ?? null) : null;
  const token = useSession ? (options.token ?? sessionToken) : null;

  // One controller for both our timeout and the caller's (React Query's) cancellation.
  const controller = new AbortController();
  let timedOut = false;
  const timer = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, timeoutMs);
  const onCallerAbort = () => controller.abort();
  if (signal?.aborted) controller.abort();
  signal?.addEventListener("abort", onCallerAbort, { once: true });

  const headers: Record<string, string> = { Accept: "application/json" };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (token) headers.Authorization = `Bearer ${token}`;

  let response: Response;
  try {
    response = await fetch(buildUrl(path, query), {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: controller.signal,
    });
  } catch (cause) {
    if (timedOut) {
      throw new ApiError({
        kind: "timeout",
        code: "TIMEOUT",
        message: "The request timed out.",
        status: 0,
      });
    }
    if (signal?.aborted) throw cause; // Cancelled by the caller: not an error to show.
    throw new ApiError({
      kind: "network",
      code: "NETWORK_ERROR",
      message: "The server could not be reached.",
      status: 0,
    });
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener("abort", onCallerAbort);
  }

  const requestId = response.headers.get("X-Request-ID");
  let envelope: Envelope<T> | null = null;
  try {
    envelope = (await response.json()) as Envelope<T>;
  } catch {
    envelope = null;
  }

  // An ok envelope is data even on a non-2xx status: GET /health/ready answers 503 with
  // {ready: false, ...} so that probes can act on the status code alone (docs/api §2).
  if (envelope && envelope.status === "ok") return envelope.data;

  if (envelope && envelope.status === "error") {
    if (response.status === 401 && sessionToken) bridge?.onUnauthorized();
    throw new ApiError({
      kind: envelope.error.kind,
      code: envelope.error.code,
      message: envelope.error.message,
      details: envelope.error.details,
      status: response.status,
      requestId: envelope.meta?.request_id ?? requestId,
      retryAfter: parseRetryAfter(response.headers.get("Retry-After")),
    });
  }

  // Not our envelope: a proxy error page, an empty body, or a contract break.
  throw new ApiError({
    kind: response.status >= 500 || response.ok ? "internal" : "client",
    code: "BAD_RESPONSE",
    message: "The server sent an unexpected response.",
    status: response.status,
    requestId,
  });
}
