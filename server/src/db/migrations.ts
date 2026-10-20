/**
 * MongoDB schema migrations (Part 08 R2.4). Each migration is declarative (a collection with
 * its $jsonSchema validator and indexes), applied in order and recorded in `_migrations`
 * with a checksum, like the SQLite runner (backend/.../db/migrate.py):
 *   - local/test apply pending migrations at startup;
 *   - staging/production refuse to start while any is pending (`npm run db:migrate` first,
 *     after a backup);
 *   - an applied migration that has since been edited is an error, never silently re-run.
 *
 * Validators enforce the exact shared vocabulary (NORMAL / HEATWAVE / SEVERE_HEATWAVE), so
 * the rule holds for any writer, not only this API.
 */
import { createHash } from "node:crypto";
import type { mongo } from "mongoose";

type Db = mongo.Db;
type IndexDescription = mongo.IndexDescription;

export interface Migration {
  id: number;
  name: string;
  collection: string;
  validator: Record<string, unknown>;
  indexes: IndexDescription[];
}

export const RISK_CLASSES = ["NORMAL", "HEATWAVE", "SEVERE_HEATWAVE"] as const;
const LEAD = { bsonType: "int", minimum: 0, maximum: 3 };
const DATE_STRING = { bsonType: "string", pattern: "^\\d{4}-\\d{2}-\\d{2}$" };
const REGION_ID = { bsonType: "string", pattern: "^[a-z][a-z0-9_]{1,40}$" };

export const MIGRATIONS: readonly Migration[] = [
  {
    id: 1,
    name: "places",
    collection: "places",
    validator: {
      $jsonSchema: {
        bsonType: "object",
        required: ["_id", "name", "district", "state", "zone", "lat", "lon", "kind", "updated_at"],
        properties: {
          _id: REGION_ID,
          name: { bsonType: "string" },
          district: { bsonType: "string" },
          state: { bsonType: "string" },
          zone: { bsonType: "string" },
          lat: { bsonType: ["double", "int"], minimum: -90, maximum: 90 },
          lon: { bsonType: ["double", "int"], minimum: -180, maximum: 180 },
          division: { bsonType: ["string", "null"] },
          kind: { enum: ["city", "area"] },
          parent: { bsonType: ["string", "null"] },
          updated_at: { bsonType: "date" },
        },
      },
    },
    indexes: [{ key: { division: 1 }, name: "division" }],
  },
  {
    id: 2,
    name: "predictions",
    collection: "predictions",
    validator: {
      $jsonSchema: {
        bsonType: "object",
        required: [
          "_id",
          "region_id",
          "lead_days",
          "valid_date",
          "issued_at",
          "created_at",
          "risk_class",
          "model_version",
          "data",
        ],
        properties: {
          _id: { bsonType: "string", pattern: "^pred_[0-9a-f]{16}$" },
          region_id: REGION_ID,
          lead_days: LEAD,
          valid_date: DATE_STRING,
          issued_at: { bsonType: "date" },
          created_at: { bsonType: "date" },
          risk_class: { enum: [...RISK_CLASSES] },
          model_version: { bsonType: "string" },
          // The ML service's PredictionOut, stored unchanged and served back field for field.
          data: { bsonType: "object" },
        },
      },
    },
    indexes: [
      // Latest per place and lead: the dashboard, the map and the Prediction page.
      { key: { region_id: 1, lead_days: 1, created_at: -1 }, name: "latest_per_place" },
      // Analytics: one per place-day, newest wins (Part 14 R2).
      { key: { valid_date: 1, region_id: 1 }, name: "by_valid_date" },
    ],
  },
  {
    id: 3,
    name: "weather_snapshots",
    collection: "weather_snapshots",
    validator: {
      $jsonSchema: {
        bsonType: "object",
        required: ["region_id", "valid_date", "lead_days", "source", "issued_at", "fetched_at"],
        properties: {
          region_id: REGION_ID,
          valid_date: DATE_STRING,
          lead_days: LEAD,
          source: { bsonType: "string" },
          issued_at: { bsonType: "date" },
          fetched_at: { bsonType: "date" },
          tmax_c: { bsonType: ["double", "int", "null"] },
          normal_tmax_c: { bsonType: ["double", "int", "null"] },
          temp_deviation_c: { bsonType: ["double", "int", "null"] },
          rh_pct: { bsonType: ["double", "int", "null"] },
          wind_ms: { bsonType: ["double", "int", "null"] },
          solar_mj_m2: { bsonType: ["double", "int", "null"] },
          precip_mm: { bsonType: ["double", "int", "null"] },
        },
      },
    },
    indexes: [
      {
        key: { region_id: 1, valid_date: 1, lead_days: 1, source: 1 },
        name: "one_per_place_day_lead_source",
        unique: true,
      },
    ],
  },
  {
    id: 4,
    name: "model_metadata",
    collection: "model_metadata",
    validator: {
      $jsonSchema: {
        bsonType: "object",
        required: ["_id", "explainer_id", "active", "recorded_at", "data"],
        properties: {
          _id: { bsonType: "string" },
          explainer_id: { bsonType: "string" },
          active: { bsonType: "bool" },
          recorded_at: { bsonType: "date" },
          data: { bsonType: "object" },
        },
      },
    },
    indexes: [{ key: { active: 1 }, name: "active" }],
  },
  {
    id: 5,
    name: "users",
    collection: "users",
    validator: {
      $jsonSchema: {
        bsonType: "object",
        required: [
          "_id",
          "username",
          "display_name",
          "role",
          "password_hash",
          "active",
          "created_at",
          "updated_at",
        ],
        properties: {
          _id: { bsonType: "string", pattern: "^user_[0-9a-z_]{4,40}$" },
          username: { bsonType: "string", pattern: "^[a-z0-9._-]{3,64}$" },
          display_name: { bsonType: "string", minLength: 1, maxLength: 120 },
          // One role for the mini-project (Part 15 §2); stored so a viewer role can be added.
          role: { enum: ["official"] },
          // A bcrypt hash only; plain or reversible passwords cannot be stored.
          password_hash: { bsonType: "string", pattern: "^\\$2[aby]\\$\\d{2}\\$.{53}$" },
          active: { bsonType: "bool" },
          region_ids: { bsonType: "array", items: REGION_ID },
          created_at: { bsonType: "date" },
          updated_at: { bsonType: "date" },
        },
      },
    },
    indexes: [{ key: { username: 1 }, name: "username_unique", unique: true }],
  },
  {
    id: 6,
    name: "revoked_tokens",
    collection: "revoked_tokens",
    validator: {
      $jsonSchema: {
        bsonType: "object",
        required: ["_id", "expires_at"],
        properties: { _id: { bsonType: "string" }, expires_at: { bsonType: "date" } },
      },
    },
    // Signed-out token ids are kept only until the token would have expired anyway.
    indexes: [{ key: { expires_at: 1 }, name: "expire", expireAfterSeconds: 0 }],
  },
  {
    id: 7,
    name: "observed_history",
    collection: "observed_history",
    validator: {
      $jsonSchema: {
        bsonType: "object",
        required: ["region_id", "date", "year", "month", "tmax_c", "risk_class"],
        properties: {
          region_id: REGION_ID,
          date: DATE_STRING,
          year: { bsonType: "int" },
          month: { bsonType: "int", minimum: 1, maximum: 12 },
          tmax_c: { bsonType: ["double", "int"] },
          // Labelled in Python by IMD-HW-DAILY-v1 (Part 03); never relabelled here.
          risk_class: { enum: [...RISK_CLASSES] },
        },
      },
    },
    indexes: [
      { key: { region_id: 1, date: 1 }, name: "one_per_place_day", unique: true },
      { key: { risk_class: 1, region_id: 1 }, name: "by_class" },
    ],
  },
  {
    id: 8,
    name: "alerts",
    collection: "alerts",
    validator: {
      $jsonSchema: {
        bsonType: "object",
        required: [
          "_id",
          "region_id",
          "severity",
          "status",
          "message",
          "channels",
          "created_by",
          "created_at",
          "updated_at",
          "client_request_id",
        ],
        properties: {
          _id: { bsonType: "string", pattern: "^HW-\\d{4}-\\d{4,}$" },
          region_id: REGION_ID,
          // An alert at NORMAL is refused: there is nothing to warn about.
          severity: { enum: ["HEATWAVE", "SEVERE_HEATWAVE"] },
          status: { enum: ["DRAFT", "READY", "ISSUED"] },
          message: { bsonType: "string", minLength: 10, maxLength: 1000 },
          channels: {
            bsonType: "array",
            minItems: 1,
            items: {
              bsonType: "object",
              required: ["channel", "status"],
              properties: { status: { enum: ["READY", "PENDING", "NOTIFIED", "FAILED"] } },
            },
          },
          prediction_id: { bsonType: ["string", "null"] },
          created_by: { bsonType: "string" },
          client_request_id: { bsonType: "string" },
        },
      },
    },
    indexes: [
      { key: { created_by: 1, client_request_id: 1 }, name: "idempotency", unique: true },
      { key: { status: 1 }, name: "status" },
      { key: { region_id: 1 }, name: "region" },
      { key: { created_at: -1 }, name: "newest" },
    ],
  },
  {
    id: 9,
    name: "counters",
    collection: "counters",
    validator: {},
    indexes: [],
  },
];

export function checksum(migration: Migration): string {
  return createHash("sha256").update(JSON.stringify(migration)).digest("hex").slice(0, 16);
}

export class MigrationError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "MigrationError";
  }
}

interface AppliedRecord {
  _id: number;
  name: string;
  checksum: string;
  applied_at: Date;
}

export interface MigrationStatus {
  current: number;
  pending: number[];
}

export async function migrationStatus(
  db: Db,
  migrations: readonly Migration[] = MIGRATIONS,
): Promise<MigrationStatus> {
  const applied = await db.collection<AppliedRecord>("_migrations").find().toArray();
  const byId = new Map(applied.map((a) => [a._id, a]));
  for (const migration of migrations) {
    const record = byId.get(migration.id);
    if (record && record.checksum !== checksum(migration)) {
      throw new MigrationError(
        `Migration ${migration.id} (${migration.name}) was edited after it was applied. ` +
          "Add a new migration instead.",
      );
    }
  }
  return {
    current: Math.max(0, ...applied.map((a) => a._id)),
    pending: migrations.filter((m) => !byId.has(m.id)).map((m) => m.id),
  };
}

/** Apply pending migrations in order; returns the ids applied. Idempotent. */
export async function applyMigrations(
  db: Db,
  migrations: readonly Migration[] = MIGRATIONS,
): Promise<number[]> {
  const { pending } = await migrationStatus(db, migrations);
  const applied: number[] = [];
  for (const migration of migrations.filter((m) => pending.includes(m.id))) {
    const exists = (await db.listCollections({ name: migration.collection }).toArray()).length;
    if (exists) {
      await db.command({ collMod: migration.collection, validator: migration.validator });
    } else {
      await db.createCollection(migration.collection, { validator: migration.validator });
    }
    if (migration.indexes.length > 0) {
      await db.collection(migration.collection).createIndexes(migration.indexes);
    }
    await db.collection<AppliedRecord>("_migrations").insertOne({
      _id: migration.id,
      name: migration.name,
      checksum: checksum(migration),
      applied_at: new Date(),
    });
    applied.push(migration.id);
  }
  return applied;
}
