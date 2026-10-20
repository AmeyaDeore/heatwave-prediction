/**
 * Revision 2 step 4 end to end over HTTP: the Node.js API on a real (in-memory) MongoDB with
 * a fake ML service. Covers places, weather snapshots, predictions (single, batch, only
 * missing, latest, latest-by-region, by id), validation, rate limiting, and the two
 * service-to-service failure modes (ML service down, MongoDB down).
 */
import { randomBytes } from "node:crypto";
import request from "supertest";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { createApp } from "./app.js";
import { prepareDatabase, recordModel } from "./bootstrap.js";
import { Catalog, loadPlaces, type Place } from "./catalog.js";
import { repoPath } from "./config.js";
import { Database } from "./db.js";
import { Store } from "./db/store.js";
import { RateLimiter } from "./http/ratelimit.js";
import { createLogger } from "./logger.js";
import { PredictionService } from "./services/predictions.js";
import { FakeMl } from "./test/fake-ml.js";
import { startTestMongo } from "./test/mongo.js";

const quiet = createLogger({ level: "ERROR", write: () => undefined });
const PLACES = loadPlaces(repoPath("config/regions.yaml"));
let mongo: Awaited<ReturnType<typeof startTestMongo>>;
const open: Database[] = [];

beforeAll(async () => {
  mongo = await startTestMongo();
});
afterAll(async () => {
  await Promise.all(open.map((d) => d.close()));
  await mongo?.stop();
});

async function setup(options: { places?: Place[]; predictLimit?: number; uri?: string } = {}) {
  const catalog = new Catalog(options.places ?? PLACES);
  const database = new Database(
    options.uri ?? mongo.uri(`api_${randomBytes(4).toString("hex")}`),
    quiet,
    500,
  );
  open.push(database);
  const store = new Store(() => database.native());
  const ml = new FakeMl();
  ml.regionIds = catalog.places.map((p) => p.id);
  if (!options.uri) await prepareDatabase("test", database, store, catalog, quiet);
  const app = createApp({
    config: { APP_ENV: "test" },
    database,
    logger: quiet,
    ml,
    api: {
      catalog,
      predictions: new PredictionService(catalog, ml, store),
      limiter: new RateLimiter({ predict: options.predictLimit ?? 1000 }),
    },
  });
  return { app, ml, store, database, catalog };
}

describe("places", () => {
  it("serves our proposed Maharashtra places from config, with the hierarchy fields", async () => {
    const { app, store } = await setup();
    const res = await request(app).get("/api/v1/regions");
    expect(res.status).toBe(200);
    expect(res.body.data).toHaveLength(18);
    expect(res.body.data[1]).toMatchObject({
      id: "kurla",
      kind: "area",
      parent: "mumbai",
      division: "Konkan",
    });
    expect(await store.countPlaces()).toBe(18); // mirrored into MongoDB at startup
  });
});

describe("POST /predict", () => {
  it("stores the ML service's prediction and serves it back field for field (checkpoint 3.7)", async () => {
    const { app } = await setup();
    const made = await request(app)
      .post("/api/v1/predict")
      .send({ region_id: "nagpur", lead_days: 1 });
    expect(made.status).toBe(200);
    const latest = await request(app).get(
      "/api/v1/predictions/latest?region_id=nagpur&lead_days=1",
    );
    expect(latest.body.data).toEqual(made.body.data);
    const byId = await request(app).get(`/api/v1/predictions/${made.body.data.prediction_id}`);
    expect(byId.body.data).toEqual(made.body.data);
  });

  it("rejects an unknown place before calling the ML service", async () => {
    const { app, ml } = await setup();
    const res = await request(app).post("/api/v1/predict").send({ region_id: "atlantis" });
    expect(res.status).toBe(404);
    expect(res.body.error.code).toBe("UNKNOWN_REGION");
    expect(ml.calls).toEqual([]);
  });

  it.each([
    [{}, "region_id"],
    [{ region_id: "pune", lead_days: 4 }, "lead_days"],
    [{ region_id: "pune", lead_dayz: 1 }, "body"],
    [{ region_id: "Pune!" }, "region_id"],
  ])("validates strictly and never echoes input (%o)", async (body, field) => {
    const { app } = await setup();
    const res = await request(app).post("/api/v1/predict").send(body);
    expect(res.status).toBe(422);
    expect(res.body.error.code).toBe("VALIDATION_ERROR");
    expect(res.body.error.details.map((d: { field: string }) => d.field).join()).toContain(field);
    expect(JSON.stringify(res.body)).not.toContain("Pune!");
  });

  it("answers malformed JSON with a 400, not a 500", async () => {
    const { app } = await setup();
    const res = await request(app)
      .post("/api/v1/predict")
      .set("Content-Type", "application/json")
      .send("{oops");
    expect(res.status).toBe(400);
    expect(res.body.error.code).toBe("BAD_REQUEST");
  });

  it("is rate limited with Retry-After", async () => {
    const { app } = await setup({ predictLimit: 2 });
    const codes = [];
    for (let i = 0; i < 3; i++)
      codes.push((await request(app).post("/api/v1/predict").send({ region_id: "pune" })).status);
    expect(codes).toEqual([200, 200, 429]);
    const res = await request(app).post("/api/v1/predict").send({ region_id: "pune" });
    expect(res.body.error.code).toBe("RATE_LIMITED");
    expect(Number(res.headers["retry-after"])).toBeGreaterThan(0);
  });
});

describe("POST /predictions/batch", () => {
  it("scores every place for every lead by default, in one ML call", async () => {
    const { app, ml } = await setup();
    const res = await request(app).post("/api/v1/predictions/batch").send({});
    expect(res.status).toBe(200);
    expect(res.body.data).toMatchObject({ scored: 72, skipped: 0 });
    expect(ml.calls).toEqual(["batch:72"]);
  });

  it("splits more than 100 pairs into several ML calls", async () => {
    const places = Array.from({ length: 30 }, (_, i) => ({ ...PLACES[5]!, id: `place_${i}` }));
    const { app, ml } = await setup({ places });
    const res = await request(app).post("/api/v1/predictions/batch").send({});
    expect(res.body.data.scored).toBe(120);
    expect(ml.calls).toEqual(["batch:100", "batch:20"]);
  });

  it("with only_missing, skips pairs already scored on the current forecast issue", async () => {
    const { app, ml } = await setup();
    await request(app)
      .post("/api/v1/predictions/batch")
      .send({ region_ids: ["pune", "nagpur"], lead_days: [0] });
    const again = await request(app)
      .post("/api/v1/predictions/batch")
      .send({ region_ids: ["pune", "nagpur", "akola"], lead_days: [0], only_missing: true });
    expect(again.body.data).toMatchObject({ scored: 1, skipped: 2 });
    expect(again.body.data.predictions[0].region.id).toBe("akola");
    // A new forecast issue makes everything due again.
    ml.issuedAt = "2026-10-20T14:00:00Z";
    const next = await request(app)
      .post("/api/v1/predictions/batch")
      .send({ region_ids: ["pune", "nagpur", "akola"], lead_days: [0], only_missing: true });
    expect(next.body.data).toMatchObject({ scored: 3, skipped: 0 });
  });

  it("rejects an unknown place in the batch before scoring anything", async () => {
    const { app, ml } = await setup();
    const res = await request(app)
      .post("/api/v1/predictions/batch")
      .send({ region_ids: ["pune", "atlantis"] });
    expect(res.status).toBe(404);
    expect(ml.calls).toEqual([]);
  });
});

describe("GET /predictions/latest-by-region", () => {
  it("returns the newest per place in catalog order, and lists the places with none", async () => {
    const { app } = await setup();
    await request(app)
      .post("/api/v1/predictions/batch")
      .send({ region_ids: ["chandrapur", "pune"], lead_days: [0] });
    const newer = await request(app)
      .post("/api/v1/predict")
      .send({ region_id: "pune", lead_days: 0 });
    const res = await request(app).get("/api/v1/predictions/latest-by-region?lead_days=0");
    expect(res.status).toBe(200);
    const items = res.body.data.items;
    expect(items.map((p: { region: { id: string } }) => p.region.id)).toEqual([
      "pune",
      "chandrapur",
    ]);
    expect(items[0].prediction_id).toBe(newer.body.data.prediction_id);
    expect(res.body.data.missing_region_ids).toHaveLength(16);
    expect(res.body.data.missing_region_ids).not.toContain("pune");
  });

  it("filters by division and 404s an unknown one", async () => {
    const { app } = await setup();
    const res = await request(app).get("/api/v1/predictions/latest-by-region?division=Nagpur");
    expect(res.body.data.missing_region_ids).toEqual(["nagpur", "chandrapur"]);
    const bad = await request(app).get("/api/v1/predictions/latest-by-region?division=Atlantis");
    expect(bad.status).toBe(404);
  });
});

describe("reads", () => {
  it("404s a place with no prediction yet, and an unknown prediction id", async () => {
    const { app } = await setup();
    const none = await request(app).get("/api/v1/predictions/latest?region_id=solapur");
    expect([none.status, none.body.error.code]).toEqual([404, "NOT_FOUND"]);
    const missing = await request(app).get("/api/v1/predictions/pred_0000000000000000");
    expect(missing.status).toBe(404);
  });

  it("serves weather from the ML service and keeps it as snapshots without duplicates", async () => {
    const { app, store } = await setup();
    const res = await request(app).get("/api/v1/weather?region_id=jalgaon&lead_days=2");
    expect(res.status).toBe(200);
    expect(res.body.data[0].region.id).toBe("jalgaon");
    await request(app).get("/api/v1/weather?region_id=jalgaon&lead_days=2");
    const snaps = await store.weatherSnapshots("jalgaon");
    expect(snaps).toHaveLength(1);
    expect(snaps[0]).toMatchObject({
      valid_date: "2026-10-22",
      lead_days: 2,
      tmax_c: 36.5,
      source: "open_meteo",
    });
  });
});

describe("failure modes", () => {
  it("ML service down: predictions fail clearly, stored reads still work, readiness says so", async () => {
    const { app, ml } = await setup();
    await request(app).post("/api/v1/predict").send({ region_id: "nanded" });
    ml.down = true;
    const res = await request(app).post("/api/v1/predict").send({ region_id: "nanded" });
    expect([res.status, res.body.error.code, res.body.error.kind]).toEqual([
      503,
      "ML_SERVICE_UNAVAILABLE",
      "upstream",
    ]);
    const stored = await request(app).get("/api/v1/predictions/latest?region_id=nanded");
    expect(stored.status).toBe(200);
    const ready = await request(app).get("/api/v1/health/ready");
    expect(ready.status).toBe(503);
    expect(ready.body.data).toMatchObject({
      database: "ok",
      ml_service: "unavailable",
      ready: false,
    });
  });

  it("MongoDB down: a clear 503 DATABASE_UNAVAILABLE, not a 500", async () => {
    const { app } = await setup({ uri: "mongodb://127.0.0.1:9/heatwave_test" });
    const res = await request(app).get("/api/v1/predictions/latest?region_id=pune");
    expect([res.status, res.body.error.code]).toEqual([503, "DATABASE_UNAVAILABLE"]);
    const ready = await request(app).get("/api/v1/health/ready");
    expect(ready.body.data).toMatchObject({
      database: "unavailable",
      ml_service: "ok",
      ready: false,
    });
  });

  it("readiness is 200 when MongoDB and the ML service are both up", async () => {
    const { app } = await setup();
    const res = await request(app).get("/api/v1/health/ready");
    expect(res.status).toBe(200);
    expect(res.body.data).toEqual({
      ready: true,
      database: "ok",
      ml_service: "ok",
      model_version: "fake-model-v1",
      explainer_id: null,
      weather_data: "ok",
      weather_issued_at: null,
    });
  });
});

describe("model metadata", () => {
  it("records the ML service's model once per version and switches the active one", async () => {
    const { ml, store } = await setup();
    expect(await recordModel(ml, store, quiet)).toBe(true);
    expect(await recordModel(ml, store, quiet)).toBe(true);
    expect((await store.activeModel())?.model_version).toBe("fake-model-v1");
    ml.model_ = { ...ml.model_, model_version: "fake-model-v2" };
    await recordModel(ml, store, quiet);
    expect((await store.activeModel())?.model_version).toBe("fake-model-v2");
  });

  it("reports false, without throwing, while the ML service is down", async () => {
    const { ml, store } = await setup();
    ml.down = true;
    expect(await recordModel(ml, store, quiet)).toBe(false);
  });
});
