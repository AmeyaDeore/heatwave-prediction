/**
 * The /api/v1 response envelope and error taxonomy, identical to the FastAPI service
 * (docs/api/README.md §1), so the frontend handles both the same way:
 *   {"status": "ok",    "data": ...,  "meta": {"request_id", "api_version"}}
 *   {"status": "error", "error": {"kind", "code", "message", "details"}, "meta": {...}}
 */
import type { Response } from "express";

export const API_VERSION = "v1";

export type ErrorKind = "client" | "upstream" | "internal";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly kind: ErrorKind = status >= 500 ? "internal" : "client",
    readonly details: unknown = null,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

function meta(res: Response) {
  return { request_id: String(res.locals.requestId ?? "unknown"), api_version: API_VERSION };
}

export function sendOk(res: Response, data: unknown, status = 200): void {
  res.status(status).json({ status: "ok", data, meta: meta(res) });
}

export function sendError(res: Response, error: ApiError): void {
  res.status(error.status).json({
    status: "error",
    error: { kind: error.kind, code: error.code, message: error.message, details: error.details },
    meta: meta(res),
  });
}
