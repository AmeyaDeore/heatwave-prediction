import { describe, expect, it } from "vitest";
import { ApiError } from "@/lib/api/errors";
import type { AlertOut } from "@/lib/api/types";
import { SAMPLE_ALERT } from "@/design/fixtures";
import { isDeliveryInFlight } from "./hooks";
import { MAX_QUERY_RETRIES, retryDelay, shouldRetry } from "./client";

const err = (status: number, kind: ApiError["kind"], retryAfter: number | null = null) =>
  new ApiError({ kind, code: "X", message: "x", status, retryAfter });

describe("query retry convention", () => {
  it("retries transient failures, at most twice", () => {
    expect(shouldRetry(0, err(0, "network"))).toBe(true);
    expect(shouldRetry(0, err(503, "upstream"))).toBe(true);
    expect(shouldRetry(1, err(500, "internal"))).toBe(true);
    expect(shouldRetry(MAX_QUERY_RETRIES, err(500, "internal"))).toBe(false);
  });

  it("never retries client errors (the same request would fail the same way)", () => {
    expect(shouldRetry(0, err(404, "client"))).toBe(false);
    expect(shouldRetry(0, err(422, "client"))).toBe(false);
    expect(shouldRetry(0, err(401, "client"))).toBe(false);
    expect(shouldRetry(0, new Error("not an api error"))).toBe(false);
  });

  it("backs off exponentially, capped, and honours Retry-After", () => {
    expect(retryDelay(0, err(500, "internal"))).toBe(1_000);
    expect(retryDelay(1, err(500, "internal"))).toBe(2_000);
    expect(retryDelay(10, err(500, "internal"))).toBe(8_000);
    expect(retryDelay(0, err(429, "client", 7))).toBe(7_000);
  });
});

describe("delivery polling rule (Part 09: poll while pending > 0)", () => {
  it("polls only an issued alert with pending channels", () => {
    expect(isDeliveryInFlight(SAMPLE_ALERT)).toBe(true);
    const done: AlertOut = {
      ...SAMPLE_ALERT,
      delivery_summary: { ...SAMPLE_ALERT.delivery_summary, pending: 0 },
    };
    expect(isDeliveryInFlight(done)).toBe(false);
    const draft: AlertOut = { ...SAMPLE_ALERT, status: "DRAFT" };
    expect(isDeliveryInFlight(draft)).toBe(false);
    expect(isDeliveryInFlight(undefined)).toBe(false);
  });
});
