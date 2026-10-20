/** Fetch stubbing helpers: respond the way the real API does (envelope, X-Request-ID). */
import { vi } from "vitest";

export function okResponse(
  data: unknown,
  init: { status?: number; headers?: Record<string, string> } = {},
) {
  return new Response(
    JSON.stringify({ status: "ok", data, meta: { request_id: "req-ok", api_version: "v1" } }),
    {
      status: init.status ?? 200,
      headers: { "Content-Type": "application/json", "X-Request-ID": "req-ok", ...init.headers },
    },
  );
}

export function errorResponse(
  status: number,
  error: { kind: string; code: string; message: string; details?: unknown },
  headers: Record<string, string> = {},
) {
  return new Response(
    JSON.stringify({
      status: "error",
      error: { details: null, ...error },
      meta: { request_id: "req-err" },
    }),
    {
      status,
      headers: { "Content-Type": "application/json", "X-Request-ID": "req-err", ...headers },
    },
  );
}

type Handler = (url: URL, init: RequestInit) => Response | Promise<Response>;

/** Route fetch by "METHOD /path" (path relative to /api/v1). Unmatched calls are a 404 envelope. */
export function stubApi(routes: Record<string, Handler | unknown>) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const url = new URL(String(input));
    const key = `${init.method ?? "GET"} ${url.pathname.replace(/^\/api\/v1/, "")}`;
    const route = routes[key];
    if (route === undefined) {
      return errorResponse(404, {
        kind: "client",
        code: "NOT_FOUND",
        message: `No stub for ${key}`,
      });
    }
    return typeof route === "function" ? (route as Handler)(url, init) : okResponse(route);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}
