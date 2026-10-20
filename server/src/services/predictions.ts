/**
 * Predictions and weather (Part 07 §B): validate the place, ask the ML service, store the
 * answer in MongoDB, return it unchanged. The ML service computes everything; this layer only
 * persists and serves (master plan §2.1).
 */
import type { Catalog } from "../catalog.js";
import type { Store } from "../db/store.js";
import { ApiError } from "../http/envelope.js";
import type { MlService, PredictionPayload, WeatherPayload } from "../ml/client.js";

export const ALL_LEADS = [0, 1, 2, 3] as const;
const ML_BATCH_LIMIT = 100; // the ML service's MAX_BATCH_ITEMS

export interface BatchRequest {
  region_ids?: string[];
  lead_days?: number[];
  /** Skip pairs already scored on the current forecast issue (the dashboard button). */
  only_missing?: boolean;
}

export interface BatchResult {
  scored: number;
  skipped: number;
  predictions: PredictionPayload[];
}

export class PredictionService {
  constructor(
    private readonly catalog: Catalog,
    private readonly ml: MlService,
    private readonly store: Store,
  ) {}

  /** 404 UNKNOWN_REGION before any call, with the FastAPI service's wording. */
  requirePlace(regionId: string): void {
    if (!this.catalog.has(regionId)) {
      throw new ApiError(404, "UNKNOWN_REGION", `Unknown region '${regionId}'.`);
    }
  }

  async predict(regionId: string, leadDays: number): Promise<PredictionPayload> {
    this.requirePlace(regionId);
    const prediction = await this.ml.predict(regionId, leadDays);
    await this.store.savePredictions([prediction]);
    return prediction;
  }

  async scoreBatch(request: BatchRequest): Promise<BatchResult> {
    const regionIds = request.region_ids ?? this.catalog.places.map((p) => p.id);
    regionIds.forEach((id) => this.requirePlace(id));
    const leads = [...new Set(request.lead_days ?? ALL_LEADS)].sort();
    let pairs = regionIds.flatMap((region_id) =>
      leads.map((lead_days) => ({ region_id, lead_days })),
    );

    let skipped = 0;
    if (request.only_missing && pairs.length > 0) {
      // The current forecast issue per place and lead decides what is "already scored".
      const issues = new Map<string, string>();
      for (const lead of leads) {
        const readings = await this.ml.weather(undefined, lead);
        await this.store.saveWeather(readings);
        for (const w of readings) issues.set(`${w.region.id}:${lead}`, w.provenance.issued_at);
      }
      const done = await this.store.scoredOnIssue(
        pairs.flatMap((p) => {
          const issuedAt = issues.get(`${p.region_id}:${p.lead_days}`);
          return issuedAt ? [{ regionId: p.region_id, leadDays: p.lead_days, issuedAt }] : [];
        }),
      );
      const before = pairs.length;
      pairs = pairs.filter((p) => !done.has(`${p.region_id}:${p.lead_days}`));
      skipped = before - pairs.length;
    }

    const predictions: PredictionPayload[] = [];
    for (let i = 0; i < pairs.length; i += ML_BATCH_LIMIT) {
      const scored = await this.ml.predictBatch(pairs.slice(i, i + ML_BATCH_LIMIT));
      await this.store.savePredictions(scored);
      predictions.push(...scored);
    }
    return { scored: predictions.length, skipped, predictions };
  }

  async latest(regionId: string, leadDays: number): Promise<PredictionPayload> {
    this.requirePlace(regionId);
    const found = await this.store.latestPrediction(regionId, leadDays);
    if (!found) {
      throw new ApiError(
        404,
        "NOT_FOUND",
        `No prediction has been made for '${regionId}' at lead ${leadDays}.`,
      );
    }
    return found;
  }

  /** The map/table/metric-card snapshot in one call (Part 11 §4), in catalog order. */
  async latestByRegion(leadDays: number, division?: string) {
    const places = this.catalog.inDivision(division);
    if (division !== undefined && places.length === 0) {
      throw new ApiError(404, "NOT_FOUND", `No monitored place is in division '${division}'.`);
    }
    const latest = await this.store.latestByRegion(
      leadDays,
      places.map((p) => p.id),
    );
    return {
      lead_days: leadDays,
      items: places.flatMap((p) => latest.get(p.id) ?? []),
      missing_region_ids: places.filter((p) => !latest.has(p.id)).map((p) => p.id),
    };
  }

  async byId(predictionId: string): Promise<PredictionPayload> {
    const found = await this.store.prediction(predictionId);
    if (!found)
      throw new ApiError(404, "NOT_FOUND", `Prediction '${predictionId}' does not exist.`);
    return found;
  }

  /** Conditions from the ML service (its shared feature path), kept as weather snapshots. */
  async weather(regionId: string | undefined, leadDays: number): Promise<WeatherPayload[]> {
    if (regionId !== undefined) this.requirePlace(regionId);
    const readings = await this.ml.weather(regionId, leadDays);
    await this.store.saveWeather(readings);
    return readings;
  }
}
