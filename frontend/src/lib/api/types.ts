/**
 * TypeScript mirror of the /api/v1 contract (docs/api/README.md, docs/api/openapi.json).
 * Field names are the API's, unchanged. If the backend schema changes, change it here in the
 * same PR; src/lib/api/contract.test.ts checks the fixtures typed with these against openapi.json.
 */
import type { RiskClass } from "@/design/labels";

export type { RiskClass };
export type AlertSeverity = Exclude<RiskClass, "NORMAL">;
export type AlertStatus = "DRAFT" | "READY" | "ISSUED";
export type DeliveryStatus = "READY" | "NOTIFIED" | "PENDING" | "FAILED";
export type ErrorKind = "client" | "upstream" | "internal";

export interface Meta {
  request_id: string;
  api_version?: string;
}

export interface ApiErrorBody {
  kind: ErrorKind;
  code: string;
  message: string;
  details: unknown;
}

export type Envelope<T> =
  { status: "ok"; data: T; meta: Meta } | { status: "error"; error: ApiErrorBody; meta: Meta };

export interface RegionOut {
  id: string;
  name: string;
  district: string;
  state: string;
  zone: string;
  lat: number;
  lon: number;
  /** Revision 2 (Part 02 R2.2): Maharashtra division, city/area, and an area's city. */
  division?: string | null;
  kind?: "city" | "area";
  parent?: string | null;
}

export interface WeatherProvenance {
  source: string;
  issued_at: string;
  age_hours: number;
  stale: boolean;
}

export interface ForecastWindow {
  valid_date: string;
  lead_days: number;
  issued_at: string;
  horizon_days?: number;
}

export type FactorDirection = "increases_risk" | "decreases_risk" | "neutral";

/** One SHAP factor, Part 06's contract unchanged (docs/ml/explainability.md §3). */
export interface FactorOut {
  rank: number;
  feature: string;
  label: string;
  unit: string;
  value: number;
  display_value: string;
  imputed: boolean;
  contribution: number;
  /** Signed; |share_pct| is the bar length and the sign its direction. Never re-derive it. */
  share_pct: number;
  direction: FactorDirection;
}

export interface ExplanationOut {
  target_class: RiskClass;
  reference_class: RiskClass;
  quantity: string;
  explained: string;
  baseline: number;
  output: number;
  factors: FactorOut[];
  summary: string;
  model_version: string;
  explainer_id: string;
}

export interface PredictionInputs {
  tmax_c: number | null;
  normal_tmax_c: number | null;
  rh_pct: number | null;
  wind_ms: number | null;
  solar_mj_m2: number | null;
  precip_mm: number | null;
  temp_deviation_c: number | null;
}

export interface PredictionOut {
  prediction_id: string;
  created_at: string;
  region: RegionOut;
  forecast_window: ForecastWindow;
  risk_class: RiskClass;
  confidence: number;
  probabilities: Record<RiskClass, number>;
  inputs: PredictionInputs;
  explanation: ExplanationOut;
  recommended_actions: string[];
  actions_version: string;
  weather: WeatherProvenance;
}

export interface WeatherOut {
  region: RegionOut;
  date: string;
  lead_days: number;
  tmax_c: number | null;
  normal_tmax_c: number | null;
  temp_deviation_c: number | null;
  rh_pct: number | null;
  wind_ms: number | null;
  solar_mj_m2: number | null;
  precip_mm: number | null;
  provenance: WeatherProvenance;
}

export interface ChannelDelivery {
  channel: string;
  label: string;
  status: DeliveryStatus;
  detail?: string | null;
  updated_at: string;
}

export interface DeliverySummary {
  total: number;
  notified: number;
  failed: number;
  pending: number;
  all_delivered: boolean;
}

export interface AlertOut {
  alert_id: string;
  status: AlertStatus;
  severity: AlertSeverity;
  region: RegionOut;
  message: string;
  prediction_id: string | null;
  channels: ChannelDelivery[];
  delivery_summary: DeliverySummary;
  created_at: string;
  created_by: string;
  issued_at: string | null;
  updated_at: string;
  idempotent_replay?: boolean;
}

export interface AlertList {
  alerts: AlertOut[];
  total: number;
  limit: number;
  offset: number;
}

export interface AlertCreate {
  client_request_id: string;
  region_id: string;
  severity: AlertSeverity;
  message: string;
  channels: string[];
  status?: AlertStatus;
  prediction_id?: string | null;
}

export interface AlertUpdate {
  severity?: AlertSeverity | null;
  message?: string | null;
  channels?: string[] | null;
  status?: AlertStatus | null;
}

export interface ChannelOut {
  id: string;
  label: string;
  mechanism: "sms" | "email" | "in_app";
}

export interface NotificationAttemptOut {
  channel: string;
  mechanism: string;
  provider: string;
  recipient: string | null;
  attempt: number;
  outcome: "SUCCESS" | "TRANSIENT_FAILURE" | "PERMANENT_FAILURE";
  detail: string | null;
  provider_ref: string | null;
  started_at: string;
  duration_ms: number;
}

export interface AdvisoryOut {
  alert_id: string;
  channel: string;
  region_id: string;
  severity: AlertSeverity;
  title: string;
  body: string;
  published_at: string;
}

export interface TrendPoint {
  date: string;
  avg_tmax_c: number;
  max_tmax_c: number;
  predictions: number;
}

export interface MonthlyCount {
  month: string;
  heatwave_events: number;
  severe_events: number;
}

export interface ModelPerformance {
  model_version: string;
  model_family: string;
  explainer_id: string;
  labeling_rule_version: string;
  evaluated_on: string;
  test_rows: number;
  accuracy: number;
  precision_macro: number;
  recall_macro: number;
  f1_macro: number;
  per_class: Record<string, Record<string, number>>;
  mean_confidence: number;
  calibration_ece: number;
}

export interface AnalyticsOut {
  period_days: number;
  region_id: string | null;
  data_source: "stored_predictions";
  temperature_trend: TrendPoint[];
  events_per_month: MonthlyCount[];
  risk_distribution: Record<RiskClass, number>;
  predictions_in_period: number;
  model_performance: ModelPerformance;
}

export interface ReadinessOut {
  ready: boolean;
  model_version: string;
  explainer_id: string;
  weather_data: "ok" | "stale" | "unavailable";
  weather_issued_at: string | null;
}

export interface UserOut {
  id: string;
  username: string;
  display_name: string;
  role: string;
}

export interface TokenOut {
  access_token: string;
  token_type?: "bearer";
  expires_at: string;
  user: UserOut;
}

/** GET /predictions/latest-by-region (Node.js API, Revision 2): the map/table snapshot. */
export interface LatestByRegionOut {
  lead_days: number;
  items: PredictionOut[];
  missing_region_ids: string[];
}

/** POST /predictions/batch (Node.js API, Revision 2). */
export interface BatchScoreOut {
  scored: number;
  skipped: number;
  predictions: PredictionOut[];
}

/** GET /analytics/place (Node.js API, Part 14 R2): observed history and stored predictions. */
export interface PlaceAnalyticsOut {
  region_id: string;
  observed: {
    source: string;
    from: string;
    to: string;
    days: number;
    shares_series_with: string[];
    per_year: { year: number; days: number; heatwave_days: number; severe_days: number }[];
    heatwave_days_per_decade_trend: number | null;
    per_month: {
      month: number;
      hot_day_share: number;
      hot_days: number;
      mean_tmax_c: number;
      mean_normal_tmax_c: number | null;
    }[];
    records: {
      hottest_day: { date: string; tmax_c: number };
      largest_departure: { date: string; temp_deviation_c: number | null };
      longest_spell: { days: number; start: string | null; end: string | null };
      heatwave_days: number;
    };
  };
  predicted: {
    source: string;
    by_lead: {
      lead_days: number;
      total: number;
      NORMAL: number;
      HEATWAVE: number;
      SEVERE_HEATWAVE: number;
    }[];
  };
}

/** GET /analytics/places: one row per selected place. */
export interface PlacesAnalyticsOut {
  source: string;
  places: {
    region_id: string;
    name: string;
    division: string | null;
    zone: string;
    observed_years: number;
    heatwave_days: number;
    severe_days: number;
    heatwave_days_per_year: number | null;
    max_tmax_c: number | null;
    shares_series_with: string[];
    latest_predicted_risk: RiskClass | null;
  }[];
}
