import request from "supertest";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { createApp } from "./app.js";
import { Database } from "./db.js";
import { createLogger } from "./logger.js";
import { startTestMongo } from "./test/mongo.js";

const quiet = createLogger({ level: "ERROR", write: () => undefined });

describe("Database against a real (in-memory) MongoDB", () => {
  let mongo: Awaited<ReturnType<typeof startTestMongo>>;

  beforeAll(async () => {
    mongo = await startTestMongo();
  });
  afterAll(async () => {
    await mongo?.stop();
  });

  it("connects, pings and reports server facts without writing anything", async () => {
    const database = new Database(mongo.uri("heatwave_test"), quiet);
    try {
      expect(await database.ping()).toBe(true);
      const info = await database.info();
      expect(info.version).toMatch(/^7\.0\./);
      expect(info.database).toBe("heatwave_test");
      expect(info.collections).toBe(0);
    } finally {
      await database.close();
    }
  });

  it("reuses one connection across pings", async () => {
    const database = new Database(mongo.uri("heatwave_test"), quiet);
    try {
      const first = await database.connect();
      await database.ping();
      expect(await database.connect()).toBe(first);
    } finally {
      await database.close();
    }
  });

  it("makes the API ready end to end", async () => {
    const database = new Database(mongo.uri("heatwave_test"), quiet);
    try {
      const app = createApp({ config: { APP_ENV: "test" }, database, logger: quiet });
      const res = await request(app).get("/api/v1/health/ready");
      expect(res.status).toBe(200);
      expect(res.body.data).toEqual({ ready: true, database: "ok" });
    } finally {
      await database.close();
    }
  });
});

describe("Database when MongoDB is unreachable", () => {
  it("reports false instead of throwing, within the timeout", async () => {
    // Port 9 (discard) on loopback: nothing listens there.
    const database = new Database("mongodb://127.0.0.1:9/heatwave_test", quiet, 500);
    const started = Date.now();
    expect(await database.ping()).toBe(false);
    expect(Date.now() - started).toBeLessThan(5_000);
    await database.close();
  });

  it("logs the failure as a warning", async () => {
    const lines: Record<string, unknown>[] = [];
    const logger = createLogger({ level: "DEBUG", write: (line) => lines.push(JSON.parse(line)) });
    const database = new Database("mongodb://127.0.0.1:9/heatwave_test", logger, 500);
    await database.ping();
    await database.close();
    expect(lines.some((l) => l.level === "WARNING" && l.msg === "database ping failed")).toBe(true);
  });
});
