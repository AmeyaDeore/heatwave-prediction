/** Steps 8-9: alerts (M5) and analysis (M3) on the Node.js API, over HTTP, on in-memory MongoDB. */
import { randomBytes, randomUUID } from "node:crypto";
import request from "supertest";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { createApp } from "./app.js";
import { prepareDatabase } from "./bootstrap.js";
import { Catalog, loadPlaces } from "./catalog.js";
import { repoPath } from "./config.js";
import { Database } from "./db.js";
import { Store } from "./db/store.js";
import { RateLimiter } from "./http/ratelimit.js";
import { createLogger } from "./logger.js";
import { AlertService, loadChannels } from "./services/alerts.js";
import { AnalyticsService, longestSpell } from "./services/analytics.js";
import { PredictionService } from "./services/predictions.js";
import { FakeMl } from "./test/fake-ml.js";
import { startTestMongo } from "./test/mongo.js";

const quiet = createLogger({ level: "ERROR", write: () => undefined });
const catalog = new Catalog(loadPlaces(repoPath("config/regions.yaml")));
let mongo: Awaited<ReturnType<typeof startTestMongo>>;
const open: Database[] = [];
beforeAll(async () => {
  mongo = await startTestMongo();
});
afterAll(async () => {
  await Promise.all(open.map((d) => d.close()));
  await mongo?.stop();
});

async function setup() {
  const database = new Database(mongo.uri(`aa_${randomBytes(4).toString("hex")}`), quiet);
  open.push(database);
  const db = () => database.native();
  const store = new Store(db);
  await prepareDatabase("test", database, store, catalog, quiet);
  const ml = new FakeMl();
  const alerts = new AlertService(
    db,
    catalog,
    loadChannels(repoPath("config/alert_channels.yaml")),
    quiet,
    0,
  );
  const app = createApp({
    config: { APP_ENV: "test" },
    database,
    logger: quiet,
    ml,
    api: {
      catalog,
      predictions: new PredictionService(catalog, ml, store),
      limiter: new RateLimiter({ predict: 1000, alerts: 1000 }),
      alerts,
      analytics: new AnalyticsService(db, catalog, store),
    },
  });
  // Routes alone (no auth): the creator id comes from requireAuth in the app; here a stand-in.
  return { app, db, store, alerts };
}

const body = (extra: Record<string, unknown> = {}) => ({
  client_request_id: randomUUID(),
  region_id: "nagpur",
  severity: "HEATWAVE",
  message: "Heatwave expected in Nagpur. Avoid outdoor work 12-4 PM.",
  channels: ["public_mobile", "hospitals"],
  ...extra,
});
const waitFor = async (check: () => Promise<boolean>) => {
  for (let i = 0; i < 50; i++) {
    if (await check()) return;
    await new Promise((r) => setTimeout(r, 20));
  }
  throw new Error("timed out");
};

describe("alerts (M5)", () => {
  it("creates a draft with READY channels and a human-readable id", async () => {
    const { app } = await setup();
    const res = await request(app).post("/api/v1/alerts").send(body());
    expect(res.status).toBe(201);
    expect(res.body.data).toMatchObject({
      alert_id: expect.stringMatching(/^HW-\d{4}-0001$/),
      status: "DRAFT",
      severity: "HEATWAVE",
      region: { id: "nagpur", name: "Nagpur" },
      issued_at: null,
    });
    expect(res.body.data.channels.map((c: { status: string }) => c.status)).toEqual([
      "READY",
      "READY",
    ]);
  });

  it("issuing goes PENDING, then every channel NOTIFIED by mock delivery", async () => {
    const { app } = await setup();
    const id = (await request(app).post("/api/v1/alerts").send(body())).body.data.alert_id;
    const issued = await request(app).patch(`/api/v1/alerts/${id}`).send({ status: "ISSUED" });
    expect(issued.body.data.status).toBe("ISSUED");
    expect(issued.body.data.issued_at).not.toBeNull();
    await waitFor(
      async () =>
        (await request(app).get(`/api/v1/alerts/${id}`)).body.data.delivery_summary.all_delivered,
    );
    const done = (await request(app).get(`/api/v1/alerts/${id}`)).body.data;
    expect(
      done.channels.every(
        (c: { status: string; detail: string }) =>
          c.status === "NOTIFIED" && c.detail.includes("no real message sent"),
      ),
    ).toBe(true);
  });

  it("an issued alert cannot be changed", async () => {
    const { app } = await setup();
    const id = (
      await request(app)
        .post("/api/v1/alerts")
        .send(body({ status: "ISSUED" }))
    ).body.data.alert_id;
    const res = await request(app)
      .patch(`/api/v1/alerts/${id}`)
      .send({ message: "Changed after the fact." });
    expect([res.status, res.body.error.code]).toEqual([409, "CONFLICT"]);
  });

  it("a repeated submission returns the first alert and notifies nobody again", async () => {
    const { app } = await setup();
    const first = body({ status: "ISSUED" });
    const a = await request(app).post("/api/v1/alerts").send(first);
    const b = await request(app).post("/api/v1/alerts").send(first);
    expect([a.status, b.status]).toEqual([201, 200]);
    expect(b.body.data.alert_id).toBe(a.body.data.alert_id);
    expect(b.body.data.idempotent_replay).toBe(true);
    expect((await request(app).get("/api/v1/alerts")).body.data.total).toBe(1);
  });

  it.each([
    [{ severity: "NORMAL" }, 422],
    [{ message: "short" }, 422],
    [{ channels: [] }, 422],
    [{ channels: ["carrier_pigeon"] }, 400],
    [{ region_id: "atlantis" }, 404],
  ])("rejects %o", async (bad, status) => {
    const { app } = await setup();
    expect((await request(app).post("/api/v1/alerts").send(body(bad))).status).toBe(status);
  });

  it("lists newest first and filters by status and place", async () => {
    const { app } = await setup();
    await request(app).post("/api/v1/alerts").send(body());
    await request(app)
      .post("/api/v1/alerts")
      .send(body({ region_id: "pune", status: "ISSUED" }));
    const all = (await request(app).get("/api/v1/alerts")).body.data;
    expect(all.alerts.map((a: { region: { id: string } }) => a.region.id)).toEqual([
      "pune",
      "nagpur",
    ]);
    expect((await request(app).get("/api/v1/alerts?status=DRAFT")).body.data.total).toBe(1);
    expect((await request(app).get("/api/v1/alerts?region_id=pune")).body.data.total).toBe(1);
  });

  it("finishes deliveries a stop interrupted", async () => {
    const { app, db, alerts } = await setup();
    const id = (await request(app).post("/api/v1/alerts").send(body())).body.data.alert_id;
    await (
      await db()
    )
      .collection("alerts")
      .updateOne(
        { _id: id as never },
        { $set: { status: "ISSUED", "channels.$[].status": "PENDING" } },
      );
    expect(await alerts.resumePending()).toBe(1);
    await waitFor(
      async () =>
        (await request(app).get(`/api/v1/alerts/${id}`)).body.data.delivery_summary.pending === 0,
    );
  });
});

describe("analysis (M3)", () => {
  async function seedHistory(db: () => Promise<import("mongoose").mongo.Db>) {
    const rows = [];
    for (const [region, base] of [
      ["nagpur", 40],
      ["akola", 39],
      ["amravati", 39],
    ] as const) {
      for (let y = 2000; y <= 2011; y++) {
        for (let d = 1; d <= 3; d++) {
          const hot = region === "nagpur" && y >= 2009 && d <= y - 2008; // more hot days in later years
          rows.push({
            region_id: region,
            date: `${y}-05-0${d}`,
            year: y,
            month: 5,
            tmax_c: hot ? 45.5 : base + d / 10,
            normal_tmax_c: 40,
            temp_deviation_c: hot ? 5.5 : base - 40 + d / 10,
            risk_class: hot ? "HEATWAVE" : "NORMAL",
          });
        }
      }
    }
    await (await db()).collection("observed_history").insertMany(rows);
  }

  it("summarises a place's observed history: per year, trend, records, spell", async () => {
    const { app, db } = await setup();
    await seedHistory(db);
    const res = await request(app).get("/api/v1/analytics/place?region_id=nagpur");
    expect(res.status).toBe(200);
    const o = res.body.data.observed;
    expect(o.per_year).toHaveLength(12);
    expect(o.per_year.at(-1)).toMatchObject({ year: 2011, heatwave_days: 3 });
    expect(o.heatwave_days_per_decade_trend).toBeGreaterThan(0);
    expect(o.records.heatwave_days).toBe(6);
    expect(o.records.longest_spell).toEqual({ days: 3, start: "2011-05-01", end: "2011-05-03" });
    expect(o.records.hottest_day.tmax_c).toBe(45.5);
    expect(o.shares_series_with).toEqual([]);
  });

  it("flags places with identical observed series (a shared IMD cell)", async () => {
    const { app, db } = await setup();
    await seedHistory(db);
    const akola = (await request(app).get("/api/v1/analytics/place?region_id=akola")).body.data;
    expect(akola.observed.shares_series_with).toEqual(["amravati"]);
  });

  it("compares places, with the latest predicted risk kept separate", async () => {
    const { app, db } = await setup();
    await seedHistory(db);
    await request(app).post("/api/v1/predict").send({ region_id: "nagpur" });
    const places = (await request(app).get("/api/v1/analytics/places?division=Nagpur")).body.data
      .places;
    expect(places.map((p: { region_id: string }) => p.region_id)).toEqual(["nagpur", "chandrapur"]);
    expect(places[0]).toMatchObject({
      heatwave_days: 6,
      observed_years: 12,
      heatwave_days_per_year: 0.5,
      latest_predicted_risk: "NORMAL",
    });
    expect(places[1]).toMatchObject({
      heatwave_days: 0,
      observed_years: 0,
      heatwave_days_per_year: null,
      latest_predicted_risk: null,
    });
  });

  it("says plainly when a place has no history yet", async () => {
    const { app } = await setup();
    const res = await request(app).get("/api/v1/analytics/place?region_id=pune");
    expect([res.status, res.body.error.code]).toEqual([404, "NOT_FOUND"]);
    expect(res.body.error.message).toContain("import-history");
  });

  it("finds the longest run of consecutive days", () => {
    expect(longestSpell([])).toEqual({ days: 0, start: null, end: null });
    expect(
      longestSpell(["2020-05-01", "2020-05-02", "2020-05-04", "2020-05-05", "2020-05-06"]),
    ).toEqual({ days: 3, start: "2020-05-04", end: "2020-05-06" });
  });
});
