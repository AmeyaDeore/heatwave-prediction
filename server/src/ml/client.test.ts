import { describe, expect, it } from "vitest";
import { ApiError } from "../http/envelope.js";
import { HttpMlClient } from "./client.js";

type Call = { url: string; init: RequestInit };

function stub(status: number, body: unknown, calls: Call[] = []): typeof fetch {
  return (async (url: string | URL | Request, init?: RequestInit) => {
    calls.push({ url: String(url), init: init ?? {} });
    return new Response(typeof body === "string" ? body : JSON.stringify(body), { status });
  }) as typeof fetch;
}

const ok = (data: unknown) => ({ status: "ok", data, meta: { request_id: "r" } });
const err = (kind: string, code: string) => ({
  status: "error",
  error: { kind, code, message: `${code} message`, details: null },
  meta: { request_id: "r" },
});

async function caught(promise: Promise<unknown>): Promise<ApiError> {
  try {
    await promise;
  } catch (error) {
    expect(error).toBeInstanceOf(ApiError);
    return error as ApiError;
  }
  throw new Error("expected a rejection");
}

describe("HttpMlClient", () => {
  it("sends the service token and JSON, and unwraps the envelope", async () => {
    const calls: Call[] = [];
    const client = new HttpMlClient(
      "http://ml:8000/",
      "token-123",
      1000,
      stub(200, ok([1, 2]), calls),
    );
    expect(await client.predictBatch([{ region_id: "pune", lead_days: 0 }])).toEqual([1, 2]);
    const { url, init } = calls[0]!;
    expect(url).toBe("http://ml:8000/api/v1/predict/batch");
    expect(init.method).toBe("POST");
    expect((init.headers as Record<string, string>)["X-Service-Token"]).toBe("token-123");
    expect(JSON.parse(String(init.body))).toEqual({ items: [{ region_id: "pune", lead_days: 0 }] });
  });

  it("builds the weather query", async () => {
    const calls: Call[] = [];
    const client = new HttpMlClient("http://ml:8000", "t", 1000, stub(200, ok([]), calls));
    await client.weather(undefined, 2);
    await client.weather("nagpur", 0);
    expect(calls.map((c) => c.url)).toEqual([
      "http://ml:8000/api/v1/weather?lead_days=2",
      "http://ml:8000/api/v1/weather?lead_days=0&region_id=nagpur",
    ]);
  });

  it.each([
    [404, "client", "UNKNOWN_REGION"],
    [422, "client", "VALIDATION_ERROR"],
    [503, "upstream", "WEATHER_DATA_UNAVAILABLE"],
  ])("passes a %i %s error through unchanged", async (status, kind, code) => {
    const client = new HttpMlClient("http://ml", "t", 1000, stub(status, err(kind, code)));
    const error = await caught(client.predict("pune", 0));
    expect([error.status, error.kind, error.code]).toEqual([status, kind, code]);
  });

  it.each([
    ["an internal error", stub(500, err("internal", "PREDICTION_FAILED"))],
    ["a rejected service token", stub(401, err("client", "UNAUTHORIZED"))],
    ["a non-JSON reply (e.g. a proxy page)", stub(502, "<html>bad gateway</html>")],
  ])("turns %s into ML_SERVICE_UNAVAILABLE", async (_label, fetchImpl) => {
    const error = await caught(new HttpMlClient("http://ml", "t", 1000, fetchImpl).model());
    expect([error.status, error.code, error.kind]).toEqual([
      503,
      "ML_SERVICE_UNAVAILABLE",
      "upstream",
    ]);
  });

  it("turns an unreachable service into ML_SERVICE_UNAVAILABLE", async () => {
    const refused = (async () => {
      throw new TypeError("fetch failed");
    }) as typeof fetch;
    const error = await caught(new HttpMlClient("http://ml", "t", 1000, refused).model());
    expect(error.code).toBe("ML_SERVICE_UNAVAILABLE");
    expect(error.details).toEqual({ reason: "unreachable" });
  });

  it("times out instead of hanging", async () => {
    const hang = ((_url: string, init?: RequestInit) =>
      new Promise((_resolve, reject) => {
        init?.signal?.addEventListener("abort", () =>
          reject(Object.assign(new Error("aborted"), { name: "AbortError" })),
        );
      })) as typeof fetch;
    const started = Date.now();
    const error = await caught(new HttpMlClient("http://ml", "t", 1000, hang).model());
    expect(error.details).toEqual({ reason: "timeout after 1000 ms" });
    expect(Date.now() - started).toBeLessThan(3000);
  });

  it("reports readiness, or null when unreachable, without throwing", async () => {
    const ready = { ready: true, model_version: "m", weather_data: "ok" };
    expect(
      await new HttpMlClient("http://ml", "t", 1000, stub(200, ok(ready))).readiness(),
    ).toEqual(ready);
    const refused = (async () => {
      throw new TypeError("fetch failed");
    }) as typeof fetch;
    expect(await new HttpMlClient("http://ml", "t", 1000, refused).readiness()).toBeNull();
  });
});
