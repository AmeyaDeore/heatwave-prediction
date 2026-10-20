/**
 * Data access on MongoDB (Part 08 R2) for places, predictions, weather snapshots and model
 * metadata. Collections, validators and indexes come from ./migrations.ts.
 *
 * A prediction is stored as the ML service returned it (`data`), beside the few fields the
 * indexes need, and served back from `data` unchanged: field for field (checkpoint 3.7).
 */
import type { mongo } from "mongoose";
import type { Place } from "../catalog.js";
import type { ModelPayload, PredictionPayload, WeatherPayload } from "../ml/client.js";

type Db = mongo.Db;

interface PlaceDoc extends Omit<Place, "id"> {
  _id: string;
  updated_at: Date;
}

interface PredictionDoc {
  _id: string;
  region_id: string;
  lead_days: number;
  valid_date: string;
  issued_at: Date;
  created_at: Date;
  risk_class: PredictionPayload["risk_class"];
  model_version: string;
  data: PredictionPayload;
}

export interface WeatherSnapshotDoc {
  region_id: string;
  valid_date: string;
  lead_days: number;
  source: string;
  issued_at: Date;
  fetched_at: Date;
  tmax_c: number | null;
  normal_tmax_c: number | null;
  temp_deviation_c: number | null;
  rh_pct: number | null;
  wind_ms: number | null;
  solar_mj_m2: number | null;
  precip_mm: number | null;
}

interface ModelDoc {
  _id: string;
  explainer_id: string;
  active: boolean;
  recorded_at: Date;
  data: ModelPayload;
}

const num = (value: unknown): number | null => (typeof value === "number" ? value : null);

export class Store {
  /** `db` resolves the open connection (or connects), so a store exists before MongoDB is up. */
  constructor(private readonly db: () => Promise<Db>) {}

  private async col<T extends object>(name: string) {
    return (await this.db()).collection<T>(name);
  }
  private get places() {
    return this.col<PlaceDoc>("places");
  }
  private get predictions() {
    return this.col<PredictionDoc>("predictions");
  }
  private get weather() {
    return this.col<WeatherSnapshotDoc>("weather_snapshots");
  }
  private get models() {
    return this.col<ModelDoc>("model_metadata");
  }

  // -- places -------------------------------------------------------------------------

  /** config/regions.yaml stays the source of truth; the collection mirrors it. */
  async upsertPlaces(places: readonly Place[]): Promise<number> {
    if (places.length === 0) return 0;
    const now = new Date();
    await (
      await this.places
    ).bulkWrite(
      places.map(({ id, ...rest }) => ({
        replaceOne: {
          filter: { _id: id },
          replacement: { _id: id, ...rest, updated_at: now },
          upsert: true,
        },
      })),
    );
    return places.length;
  }

  async countPlaces(): Promise<number> {
    return (await this.places).countDocuments();
  }

  // -- predictions ----------------------------------------------------------------------

  async savePredictions(payloads: readonly PredictionPayload[]): Promise<void> {
    if (payloads.length === 0) return;
    await (
      await this.predictions
    ).insertMany(
      payloads.map((p) => ({
        _id: p.prediction_id,
        region_id: p.region.id,
        lead_days: p.forecast_window.lead_days,
        valid_date: p.forecast_window.valid_date,
        issued_at: new Date(p.forecast_window.issued_at),
        created_at: new Date(p.created_at),
        risk_class: p.risk_class,
        model_version: p.explanation.model_version,
        data: p,
      })),
    );
  }

  async prediction(id: string): Promise<PredictionPayload | null> {
    return (
      (await (await this.predictions).findOne({ _id: id }, { projection: { data: 1 } }))?.data ??
      null
    );
  }

  async latestPrediction(regionId: string, leadDays: number): Promise<PredictionPayload | null> {
    const doc = await (
      await this.predictions
    ).findOne(
      { region_id: regionId, lead_days: leadDays },
      { sort: { created_at: -1 }, projection: { data: 1 } },
    );
    return doc?.data ?? null;
  }

  /** The newest stored prediction per place for one lead, in one aggregation. */
  async latestByRegion(
    leadDays: number,
    regionIds: readonly string[],
  ): Promise<Map<string, PredictionPayload>> {
    const rows = await (
      await this.predictions
    )
      .aggregate<{ _id: string; data: PredictionPayload }>([
        { $match: { lead_days: leadDays, region_id: { $in: [...regionIds] } } },
        { $sort: { region_id: 1, lead_days: 1, created_at: -1 } },
        { $group: { _id: "$region_id", data: { $first: "$data" } } },
      ])
      .toArray();
    return new Map(rows.map((r) => [r._id, r.data]));
  }

  /** (region, lead) pairs already scored on a given forecast issue (for "only missing"). */
  async scoredOnIssue(
    pairs: readonly { regionId: string; leadDays: number; issuedAt: string }[],
  ): Promise<Set<string>> {
    if (pairs.length === 0) return new Set();
    const found = await (
      await this.predictions
    )
      .find(
        {
          $or: pairs.map((p) => ({
            region_id: p.regionId,
            lead_days: p.leadDays,
            issued_at: new Date(p.issuedAt),
          })),
        },
        { projection: { region_id: 1, lead_days: 1 } },
      )
      .toArray();
    return new Set(found.map((d) => `${d.region_id}:${d.lead_days}`));
  }

  // -- weather --------------------------------------------------------------------------

  /** Keep the latest issue per place, day, lead and source (re-fetches never duplicate). */
  async saveWeather(readings: readonly WeatherPayload[]): Promise<void> {
    if (readings.length === 0) return;
    const fetchedAt = new Date();
    await (
      await this.weather
    ).bulkWrite(
      readings.map((w) => {
        const doc: WeatherSnapshotDoc = {
          region_id: w.region.id,
          valid_date: w.date,
          lead_days: w.lead_days,
          source: w.provenance.source,
          issued_at: new Date(w.provenance.issued_at),
          fetched_at: fetchedAt,
          tmax_c: num(w.tmax_c),
          normal_tmax_c: num(w.normal_tmax_c),
          temp_deviation_c: num(w.temp_deviation_c),
          rh_pct: num(w.rh_pct),
          wind_ms: num(w.wind_ms),
          solar_mj_m2: num(w.solar_mj_m2),
          precip_mm: num(w.precip_mm),
        };
        return {
          replaceOne: {
            filter: {
              region_id: doc.region_id,
              valid_date: doc.valid_date,
              lead_days: doc.lead_days,
              source: doc.source,
            },
            replacement: doc,
            upsert: true,
          },
        };
      }),
    );
  }

  async weatherSnapshots(regionId: string): Promise<WeatherSnapshotDoc[]> {
    return (await this.weather).find({ region_id: regionId }, { projection: { _id: 0 } }).toArray();
  }

  // -- model metadata -------------------------------------------------------------------

  /** Record the ML service's model once per version and mark it the active one. */
  async recordModel(model: ModelPayload): Promise<boolean> {
    const models = await this.models;
    const existing = await models.findOne({ _id: model.model_version, active: true });
    if (existing) return false;
    await models.updateMany({ active: true }, { $set: { active: false } });
    await models.replaceOne(
      { _id: model.model_version }, // the filter's _id is kept by the upsert
      {
        explainer_id: model.explainer_id,
        active: true,
        recorded_at: new Date(),
        data: model,
      },
      { upsert: true },
    );
    return true;
  }

  async activeModel(): Promise<ModelPayload | null> {
    return (await (await this.models).findOne({ active: true }))?.data ?? null;
  }
}
