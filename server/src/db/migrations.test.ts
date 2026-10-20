import { randomBytes } from "node:crypto";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { Database } from "../db.js";
import { createLogger } from "../logger.js";
import { startTestMongo } from "../test/mongo.js";
import { applyMigrations, MIGRATIONS, MigrationError, migrationStatus } from "./migrations.js";

const quiet = createLogger({ level: "ERROR", write: () => undefined });
let mongo: Awaited<ReturnType<typeof startTestMongo>>;
const open: Database[] = [];

beforeAll(async () => {
  mongo = await startTestMongo();
});
afterAll(async () => {
  await Promise.all(open.map((d) => d.close()));
  await mongo?.stop();
});

async function freshDb() {
  const database = new Database(mongo.uri(`mig_${randomBytes(4).toString("hex")}`), quiet);
  open.push(database);
  return database.native();
}

const prediction = (overrides: Record<string, unknown> = {}) => ({
  _id: "pred_0123456789abcdef",
  region_id: "nagpur",
  lead_days: 1,
  valid_date: "2026-10-21",
  issued_at: new Date(),
  created_at: new Date(),
  risk_class: "HEATWAVE",
  model_version: "m1",
  data: { any: "thing" },
  ...overrides,
});

describe("migrations", () => {
  it("creates every collection with its indexes, once", async () => {
    const db = await freshDb();
    expect(await applyMigrations(db)).toEqual(MIGRATIONS.map((m) => m.id));
    expect(await applyMigrations(db)).toEqual([]);
    expect(await migrationStatus(db)).toEqual({ current: MIGRATIONS.length, pending: [] });
    const names = (await db.listCollections().toArray()).map((c) => c.name);
    expect(names).toEqual(
      expect.arrayContaining([
        "places",
        "predictions",
        "weather_snapshots",
        "model_metadata",
        "_migrations",
      ]),
    );
    const indexes = (await db.collection("predictions").indexes()).map((i) => i.name);
    expect(indexes).toEqual(expect.arrayContaining(["latest_per_place", "by_valid_date"]));
  });

  it("refuses an applied migration that was edited afterwards", async () => {
    const db = await freshDb();
    await applyMigrations(db);
    const edited = MIGRATIONS.map((m) => (m.id === 2 ? { ...m, name: "renamed" } : m));
    await expect(migrationStatus(db, edited)).rejects.toThrow(MigrationError);
  });

  it("reports pending migrations without applying them", async () => {
    const db = await freshDb();
    expect((await migrationStatus(db)).pending).toEqual(MIGRATIONS.map((m) => m.id));
    expect((await db.listCollections({ name: "predictions" }).toArray()).length).toBe(0);
  });
});

describe("validators enforce the shared vocabulary in the database itself", () => {
  it("accepts a valid prediction", async () => {
    const db = await freshDb();
    await applyMigrations(db);
    await expect(
      db.collection("predictions").insertOne(prediction() as never),
    ).resolves.toBeTruthy();
  });

  it.each([
    { risk_class: "HIGH" },
    { risk_class: "normal" },
    { lead_days: 4 },
    { valid_date: "21/10/2026" },
    { region_id: "Nagpur" },
    { _id: "not-a-prediction-id" },
    { data: undefined },
  ])("rejects %o", async (bad) => {
    const db = await freshDb();
    await applyMigrations(db);
    await expect(db.collection("predictions").insertOne(prediction(bad) as never)).rejects.toThrow(
      /validation/i,
    );
  });

  it("enforces one weather snapshot per place, day, lead and source", async () => {
    const db = await freshDb();
    await applyMigrations(db);
    const snap = {
      region_id: "pune",
      valid_date: "2026-10-20",
      lead_days: 0,
      source: "open_meteo",
      issued_at: new Date(),
      fetched_at: new Date(),
    };
    await db.collection("weather_snapshots").insertOne({ ...snap });
    await expect(db.collection("weather_snapshots").insertOne({ ...snap })).rejects.toThrow(
      /duplicate key/,
    );
  });
});

describe("query plans use the indexes (Part 08 R2.2)", () => {
  function indexNames(plan: unknown): string[] {
    const names: string[] = [];
    const walk = (node: unknown) => {
      if (!node || typeof node !== "object") return;
      const n = node as Record<string, unknown>;
      // IXSCAN, or DISTINCT_SCAN when the planner serves a $group-$first straight from the index.
      if ((n.stage === "IXSCAN" || n.stage === "DISTINCT_SCAN") && typeof n.indexName === "string")
        names.push(n.indexName);
      Object.values(n).forEach(walk);
    };
    walk(plan);
    return names;
  }

  it("latest prediction per place and lead, and latest-by-region, use latest_per_place", async () => {
    const db = await freshDb();
    await applyMigrations(db);
    const docs = Array.from({ length: 40 }, (_, i) =>
      prediction({
        _id: `pred_${i.toString(16).padStart(16, "0")}`,
        region_id: ["pune", "nagpur", "akola", "nanded"][i % 4],
        lead_days: i % 4,
        created_at: new Date(Date.UTC(2026, 9, 1 + (i % 20))),
      }),
    );
    await db.collection("predictions").insertMany(docs as never[]);

    const single = await db
      .collection("predictions")
      .find({ region_id: "pune", lead_days: 0 })
      .sort({ created_at: -1 })
      .limit(1)
      .explain("queryPlanner");
    expect(indexNames(single)).toContain("latest_per_place");

    const grouped = await db
      .collection("predictions")
      .aggregate([
        { $match: { lead_days: 0, region_id: { $in: ["pune", "nagpur"] } } },
        { $sort: { region_id: 1, lead_days: 1, created_at: -1 } },
        { $group: { _id: "$region_id", data: { $first: "$data" } } },
      ])
      .explain("queryPlanner");
    expect(indexNames(grouped)).toContain("latest_per_place");
  });
});
