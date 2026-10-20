import { afterEach, describe, expect, it, vi } from "vitest";
import { errorResponse, okResponse } from "@/test/http";
import { apiRequest, buildUrl } from "./client";
import { api } from "./endpoints";
import { ApiError, describeError } from "./errors";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

function stubFetch(impl: (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>) {
  const mock = vi.fn(impl);
  vi.stubGlobal("fetch", mock);
  return mock;
}

describe("buildUrl", () => {
  it("prefixes /api/v1 and drops empty query values", () => {
    expect(
      buildUrl("/weather", { region_id: "mumbai", lead_days: 0, status: undefined, x: "" }),
    ).toBe("http://localhost:4000/api/v1/weather?region_id=mumbai&lead_days=0");
  });
});

describe("apiRequest", () => {
  it("unwraps the ok envelope", async () => {
    stubFetch(async () => okResponse([{ id: "mumbai" }]));
    await expect(apiRequest("/regions")).resolves.toEqual([{ id: "mumbai" }]);
  });

  it("returns data from an ok envelope even on 503 (readiness 'not ready')", async () => {
    stubFetch(async () => okResponse({ ready: false, weather_data: "stale" }, { status: 503 }));
    await expect(api.readiness()).resolves.toMatchObject({ ready: false });
  });

  it("turns an error envelope into an ApiError with code, kind, status and request id", async () => {
    stubFetch(async () =>
      errorResponse(404, {
        kind: "client",
        code: "UNKNOWN_REGION",
        message: "Unknown region 'atlantis'.",
      }),
    );
    const error = await apiRequest("/weather").catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({
      kind: "client",
      code: "UNKNOWN_REGION",
      status: 404,
      requestId: "req-err",
      message: "Unknown region 'atlantis'.",
    });
  });

  it("reads Retry-After on a 429", async () => {
    stubFetch(async () =>
      errorResponse(
        429,
        { kind: "client", code: "RATE_LIMITED", message: "Slow down." },
        { "Retry-After": "12" },
      ),
    );
    const error = (await apiRequest("/predict", { method: "POST", body: {} }).catch(
      (e: unknown) => e,
    )) as ApiError;
    expect(error.retryAfter).toBe(12);
    expect(error.isTransient).toBe(true);
  });

  it("treats a non-envelope body (proxy error page) as BAD_RESPONSE", async () => {
    stubFetch(async () => new Response("<html>Bad gateway</html>", { status: 502 }));
    await expect(apiRequest("/regions")).rejects.toMatchObject({
      code: "BAD_RESPONSE",
      kind: "internal",
    });
  });

  it("reports an unreachable server as a network error", async () => {
    stubFetch(async () => {
      throw new TypeError("Failed to fetch");
    });
    await expect(apiRequest("/regions")).rejects.toMatchObject({ kind: "network", status: 0 });
  });

  it("times out a hung request", async () => {
    vi.useFakeTimers();
    stubFetch(
      (_input, init) =>
        new Promise((_resolve, reject) => {
          init?.signal?.addEventListener("abort", () =>
            reject(new DOMException("Aborted", "AbortError")),
          );
        }),
    );
    const pending = apiRequest("/regions", { timeoutMs: 1_000 }).catch((e: unknown) => e);
    await vi.advanceTimersByTimeAsync(1_001);
    await expect(pending).resolves.toMatchObject({ kind: "timeout", code: "TIMEOUT" });
  });

  it("passes a caller's cancellation through untouched (not shown as an error)", async () => {
    stubFetch(
      (_input, init) =>
        new Promise((_resolve, reject) => {
          init?.signal?.addEventListener("abort", () =>
            reject(new DOMException("Aborted", "AbortError")),
          );
        }),
    );
    const controller = new AbortController();
    const pending = apiRequest("/regions", { signal: controller.signal }).catch((e: unknown) => e);
    controller.abort();
    const error = await pending;
    expect(error).not.toBeInstanceOf(ApiError);
    expect((error as DOMException).name).toBe("AbortError");
  });

  it("sends JSON bodies and the bearer token only when given", async () => {
    const mock = stubFetch(async () => okResponse({}));
    await api.createAlert(
      {
        client_request_id: "id",
        region_id: "mumbai",
        severity: "HEATWAVE",
        message: "0123456789",
        channels: ["hospitals"],
      },
      { token: "tok" },
    );
    const [, init] = mock.mock.calls[0]!;
    expect(init?.method).toBe("POST");
    expect((init?.headers as Record<string, string>).Authorization).toBe("Bearer tok");
    expect(JSON.parse(String(init?.body))).toMatchObject({ region_id: "mumbai" });

    await api.regions();
    const [, plain] = mock.mock.calls[1]!;
    expect((plain?.headers as Record<string, string>).Authorization).toBeUndefined();
  });
});

describe("describeError", () => {
  it("never shows codes or stack traces, and keeps the request id as a reference", () => {
    const d = describeError(
      new ApiError({
        kind: "internal",
        code: "PREDICTION_FAILED",
        message: "x",
        status: 500,
        requestId: "abc",
      }),
    );
    expect(d.title).toBe("The service had a problem");
    expect(`${d.title} ${d.description}`).not.toMatch(/PREDICTION_FAILED|Traceback/);
    expect(d.reference).toBe("abc");
    expect(d.retryable).toBe(true);
  });

  it("shows the API's own message for client errors and does not offer a pointless retry", () => {
    const d = describeError(
      new ApiError({
        kind: "client",
        code: "CONFLICT",
        message: "Create a new alert instead.",
        status: 409,
      }),
    );
    expect(d.description).toBe("Create a new alert instead.");
    expect(d.retryable).toBe(false);
  });

  it("handles non-API errors", () => {
    expect(describeError(new Error("boom")).title).toBe("Something went wrong");
  });
});
