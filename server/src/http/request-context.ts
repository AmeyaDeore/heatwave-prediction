/**
 * Per-request context, as in the FastAPI service: an X-Request-ID (the caller's, if it is a
 * plain token, otherwise 16 random hex characters) echoed on the response, and one access-log
 * line per request with method, path, status and latency.
 */
import { randomBytes } from "node:crypto";
import type { RequestHandler } from "express";
import type { Logger } from "../logger.js";

// A caller-supplied id is echoed and logged, so it must be a plain token: no spaces, quotes or
// control characters that could forge or break a log line.
const SAFE_REQUEST_ID = /^[A-Za-z0-9._-]{1,64}$/;

export function newRequestId(): string {
  return randomBytes(8).toString("hex");
}

export function requestContext(accessLog: Logger): RequestHandler {
  return (req, res, next) => {
    const supplied = req.get("X-Request-ID");
    const requestId = supplied && SAFE_REQUEST_ID.test(supplied) ? supplied : newRequestId();
    res.locals.requestId = requestId;
    res.setHeader("X-Request-ID", requestId);

    const started = process.hrtime.bigint();
    res.on("finish", () => {
      accessLog.info("request", {
        request_id: requestId,
        method: req.method,
        path: req.path,
        status: res.statusCode,
        latency_ms: Math.round(Number(process.hrtime.bigint() - started) / 1e5) / 10,
        user_id: res.locals.userId ?? null,
        // Route-specific fields (risk_class, region_id, ...), as the FastAPI log has.
        ...(res.locals.logFields as Record<string, unknown> | undefined),
      });
    });
    next();
  };
}
