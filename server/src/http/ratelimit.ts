/**
 * In-process sliding-window rate limit per client IP, as the FastAPI service has
 * (backend/.../ratelimit.py): same buckets, same 429 RATE_LIMITED envelope and Retry-After.
 * Per process: fine for one API process (docs/api/README.md §8).
 */
import type { RequestHandler } from "express";
import { ApiError } from "./envelope.js";

export class RateLimiter {
  private readonly hits = new Map<string, number[]>();

  constructor(
    private readonly limits: Record<string, number>,
    private readonly now: () => number = () => Date.now(),
  ) {}

  check(bucket: string, client: string): void {
    const limit = this.limits[bucket];
    if (limit === undefined) throw new Error(`No rate limit bucket '${bucket}'`);
    const now = this.now();
    const key = `${bucket}|${client}`;
    const recent = (this.hits.get(key) ?? []).filter((t) => now - t < 60_000);
    if (recent.length >= limit) {
      const retry = Math.max(1, Math.ceil((60_000 - (now - recent[0]!)) / 1000));
      this.hits.set(key, recent);
      const error = new ApiError(
        429,
        "RATE_LIMITED",
        `Too many requests. Try again in ${retry} seconds.`,
        "client",
        { limit_per_minute: limit, retry_after_seconds: retry },
      );
      throw Object.assign(error, { retryAfter: retry });
    }
    recent.push(now);
    this.hits.set(key, recent);
  }

  middleware(bucket: string): RequestHandler {
    return (req, res, next) => {
      try {
        this.check(bucket, req.socket.remoteAddress ?? "unknown");
        next();
      } catch (error) {
        const retry = (error as { retryAfter?: number }).retryAfter;
        if (retry) res.setHeader("Retry-After", String(retry));
        next(error);
      }
    };
  }
}
