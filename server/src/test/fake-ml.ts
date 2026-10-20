/**
 * A fake ML inference service for tests: deterministic payloads in the real contract's shape
 * (docs/api/README.md PredictionOut / WeatherOut), and a record of every call made.
 */
import { randomBytes } from "node:crypto";
import { ApiError } from "../http/envelope.js";
import type {
  MlReadiness,
  MlService,
  ModelPayload,
  PredictionPayload,
  WeatherPayload,
} from "../ml/client.js";

export const FAKE_MODEL: ModelPayload = {
  model_version: "fake-model-v1",
  model_family: "xgboost",
  explainer_id: "fake-model-v1+shap.test",
  f1_macro: 0.82,
};

const ISSUED_AT = "2026-10-20T08:00:00Z";

export class FakeMl implements MlService {
  calls: string[] = [];
  down = false;
  issuedAt = ISSUED_AT;
  model_ = FAKE_MODEL;

  private check(call: string) {
    this.calls.push(call);
    if (this.down) {
      throw new ApiError(503, "ML_SERVICE_UNAVAILABLE", "down", "upstream", { reason: "test" });
    }
  }

  payload(regionId: string, leadDays: number): PredictionPayload {
    const tmax = 38 + leadDays + (regionId === "chandrapur" ? 6 : 0);
    const risk = tmax >= 45 ? "SEVERE_HEATWAVE" : tmax >= 40 ? "HEATWAVE" : "NORMAL";
    return {
      prediction_id: `pred_${randomBytes(8).toString("hex")}`,
      created_at: new Date().toISOString(),
      region: { id: regionId, name: regionId },
      forecast_window: {
        valid_date: `2026-10-${String(20 + leadDays).padStart(2, "0")}`,
        lead_days: leadDays,
        issued_at: this.issuedAt,
        horizon_days: 3,
      },
      risk_class: risk,
      confidence: 0.9,
      probabilities: { NORMAL: 0.05, HEATWAVE: 0.05, SEVERE_HEATWAVE: 0.9 },
      inputs: { tmax_c: tmax, temp_deviation_c: tmax - 34, rh_pct: null },
      explanation: {
        model_version: this.model_.model_version,
        explainer_id: this.model_.explainer_id,
        factors: [
          { rank: 1, feature: "temp_deviation_c", share_pct: 61.5, direction: "increases_risk" },
        ],
        summary: `The model predicts ${risk}.`,
      },
      recommended_actions: ["Continue routine monitoring of the daily forecast"],
      actions_version: "RA-v1",
      weather: { source: "open_meteo", issued_at: this.issuedAt, age_hours: 2, stale: false },
    };
  }

  async predict(regionId: string, leadDays: number) {
    this.check(`predict:${regionId}:${leadDays}`);
    return this.payload(regionId, leadDays);
  }

  async predictBatch(items: { region_id: string; lead_days: number }[]) {
    this.check(`batch:${items.length}`);
    return items.map((i) => this.payload(i.region_id, i.lead_days));
  }

  regionIds: string[] = [];

  async weather(regionId: string | undefined, leadDays: number): Promise<WeatherPayload[]> {
    this.check(`weather:${regionId ?? "all"}:${leadDays}`);
    return (regionId ? [regionId] : this.regionIds).map((id) => ({
      region: { id, name: id },
      date: `2026-10-${String(20 + leadDays).padStart(2, "0")}`,
      lead_days: leadDays,
      tmax_c: 36.5,
      normal_tmax_c: 33,
      temp_deviation_c: 3.5,
      rh_pct: 60,
      wind_ms: 2.1,
      solar_mj_m2: 20,
      precip_mm: 0,
      provenance: { source: "open_meteo", issued_at: this.issuedAt, age_hours: 2, stale: false },
    }));
  }

  async model() {
    this.check("model");
    return this.model_;
  }

  async readiness(): Promise<MlReadiness | null> {
    return this.down
      ? null
      : { ready: true, model_version: this.model_.model_version, weather_data: "ok" };
  }
}
