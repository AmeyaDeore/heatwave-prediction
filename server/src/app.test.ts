import express from "express";
import request from "supertest";
import { describe, expect, it } from "vitest";
import { createApp, errorHandler } from "./app.js";
import type { DatabaseHealth } from "./db.js";
import { ApiError } from "./http/envelope.js";
import { requestContext } from "./http/request-context.js";
import { createLogger } from "./logger.js";

function captureLogger() {
  const lines: Record<string, unknown>[] = [];
  const logger = createLogger({ level: "DEBUG", write: (line) => lines.push(JSON.parse(line)) });
  return { logger, lines };
}

function appWith(database: DatabaseHealth) {
  const { logger, lines } = captureLogger();
  return { app: createApp({ config: { APP_ENV: "test" }, database, logger }), lines };
}

const up: DatabaseHealth = { ping: async () => true };
const down: DatabaseHealth = { ping: async () => false };

describe("liveness", () => {
  it("answers like the FastAPI service, without touching the database", async () => {
    let pinged = false;
    const { app } = appWith({ ping: async () => (pinged = true) });
    const res = await request(app).get("/health");
    expect(res.status).toBe(200);
    expect(res.body).toEqual({ status: "ok", env: "test" });
    expect(pinged).toBe(false);
  });
});

describe("readiness", () => {
  it("is ready when MongoDB answers", async () => {
    const res = await request(appWith(up).app).get("/api/v1/health/ready");
    expect(res.status).toBe(200);
    expect(res.body.status).toBe("ok");
    expect(res.body.data).toEqual({ ready: true, database: "ok" });
    expect(res.body.meta).toEqual({ request_id: expect.any(String), api_version: "v1" });
  });

  it("is a 503 with an ok envelope when MongoDB is down, so probes act on the status", async () => {
    const res = await request(appWith(down).app).get("/api/v1/health/ready");
    expect(res.status).toBe(503);
    expect(res.body.status).toBe("ok");
    expect(res.body.data).toEqual({ ready: false, database: "unavailable" });
  });
});

describe("request id and access log", () => {
  it("generates a 16-hex id, returns it, and logs the request", async () => {
    const { app, lines } = appWith(up);
    const res = await request(app).get("/health");
    const id = res.headers["x-request-id"];
    expect(id).toMatch(/^[0-9a-f]{16}$/);
    const access = lines.find((l) => l.logger === "heatwave_server.access");
    expect(access).toMatchObject({
      level: "INFO",
      msg: "request",
      request_id: id,
      method: "GET",
      path: "/health",
      status: 200,
      user_id: null,
    });
    expect(typeof access?.latency_ms).toBe("number");
  });

  it("echoes a caller's id into the header and the envelope", async () => {
    const res = await request(appWith(up).app)
      .get("/api/v1/health/ready")
      .set("X-Request-ID", "trace-42");
    expect(res.headers["x-request-id"]).toBe("trace-42");
    expect(res.body.meta.request_id).toBe("trace-42");
  });

  it("replaces an id that could forge a log line", async () => {
    const res = await request(appWith(up).app)
      .get("/health")
      .set("X-Request-ID", 'a" "level":"ERROR');
    expect(res.headers["x-request-id"]).toMatch(/^[0-9a-f]{16}$/);
  });
});

describe("errors", () => {
  it("answers an unknown route with the NOT_FOUND envelope", async () => {
    const res = await request(appWith(up).app).get("/api/v1/nope");
    expect(res.status).toBe(404);
    expect(res.body).toMatchObject({
      status: "error",
      error: { kind: "client", code: "NOT_FOUND", details: null },
      meta: { api_version: "v1" },
    });
  });

  it("hides unexpected errors behind INTERNAL_ERROR and logs the detail", async () => {
    const { logger, lines } = captureLogger();
    const app = express();
    app.use(requestContext(logger));
    app.get("/boom", () => {
      throw new Error("secret internals at /srv/app.ts:12");
    });
    app.use(errorHandler(logger));

    const res = await request(app).get("/boom");
    expect(res.status).toBe(500);
    expect(res.body.error.code).toBe("INTERNAL_ERROR");
    expect(res.body.error.kind).toBe("internal");
    expect(res.body.error.message).toContain(res.headers["x-request-id"]);
    expect(JSON.stringify(res.body)).not.toContain("secret internals");
    expect(
      lines.some(
        (l) => l.msg === "unhandled error" && l.error === "secret internals at /srv/app.ts:12",
      ),
    ).toBe(true);
  });

  it("passes ApiError status, code and kind through", async () => {
    const { logger } = captureLogger();
    const app = express();
    app.use(requestContext(logger));
    app.get("/upstream", () => {
      throw new ApiError(
        503,
        "ML_SERVICE_UNAVAILABLE",
        "The prediction service is unavailable.",
        "upstream",
      );
    });
    app.use(errorHandler(logger));

    const res = await request(app).get("/upstream");
    expect(res.status).toBe(503);
    expect(res.body.error).toEqual({
      kind: "upstream",
      code: "ML_SERVICE_UNAVAILABLE",
      message: "The prediction service is unavailable.",
      details: null,
    });
  });

  it("does not advertise Express", async () => {
    const res = await request(appWith(up).app).get("/health");
    expect(res.headers["x-powered-by"]).toBeUndefined();
  });
});
