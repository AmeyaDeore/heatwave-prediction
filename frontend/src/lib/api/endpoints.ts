/**
 * One typed function per backend route (docs/api §2). Paths and parameter names live here and
 * nowhere else.
 */
import { apiRequest } from "./client";
import type {
  AdvisoryOut,
  AlertCreate,
  AlertList,
  AlertOut,
  AlertStatus,
  AlertUpdate,
  AnalyticsOut,
  BatchScoreOut,
  ChannelOut,
  ModelPerformance,
  LatestByRegionOut,
  PlaceAnalyticsOut,
  PlacesAnalyticsOut,
  NotificationAttemptOut,
  PredictionOut,
  ReadinessOut,
  RegionOut,
  TokenOut,
  UserOut,
  WeatherOut,
} from "./types";

type Signal = { signal?: AbortSignal };
type Authed = { token: string };

export const api = {
  regions: (o: Signal = {}) => apiRequest<RegionOut[]>("/regions", o),
  alertChannels: (o: Signal = {}) => apiRequest<ChannelOut[]>("/alert-channels", o),
  readiness: (o: Signal = {}) => apiRequest<ReadinessOut>("/health/ready", o),

  /** Conditions for one region, or every monitored region when regionId is omitted. */
  weather: (p: { regionId?: string; leadDays?: number }, o: Signal = {}) =>
    apiRequest<WeatherOut[]>("/weather", {
      ...o,
      query: { region_id: p.regionId, lead_days: p.leadDays ?? 0 },
    }),

  /** The latest *stored* prediction (no recompute). 404 NOT_FOUND until one exists. */
  latestPrediction: (p: { regionId: string; leadDays?: number }, o: Signal = {}) =>
    apiRequest<PredictionOut>("/predictions/latest", {
      ...o,
      query: { region_id: p.regionId, lead_days: p.leadDays ?? 0 },
    }),
  /** Newest stored prediction per place for one lead, in one call (Part 11 R2). */
  latestByRegion: (p: { leadDays?: number; division?: string }, o: Signal = {}) =>
    apiRequest<LatestByRegionOut>("/predictions/latest-by-region", {
      ...o,
      query: { lead_days: p.leadDays ?? 0, division: p.division },
    }),
  /** Score places through the ML service (rate limited). only_missing: not yet scored on the
   *  current forecast issue (the dashboard's button). */
  scoreBatch: (body: { region_ids?: string[]; lead_days?: number[]; only_missing?: boolean }) =>
    apiRequest<BatchScoreOut>("/predictions/batch", { method: "POST", body }),
  prediction: (predictionId: string, o: Signal = {}) =>
    apiRequest<PredictionOut>(`/predictions/${encodeURIComponent(predictionId)}`, o),
  /** Score now (rate limited, 30/min). Stores and returns a new prediction. */
  predict: (p: { regionId: string; leadDays?: number }, o: Signal = {}) =>
    apiRequest<PredictionOut>("/predict", {
      ...o,
      method: "POST",
      body: { region_id: p.regionId, lead_days: p.leadDays ?? 0 },
    }),

  alerts: (
    p: { status?: AlertStatus; regionId?: string; limit?: number; offset?: number } = {},
    o: Signal = {},
  ) =>
    apiRequest<AlertList>("/alerts", {
      ...o,
      query: { status: p.status, region_id: p.regionId, limit: p.limit, offset: p.offset },
    }),
  alert: (alertId: string, o: Signal = {}) =>
    apiRequest<AlertOut>(`/alerts/${encodeURIComponent(alertId)}`, o),
  createAlert: (body: AlertCreate, o: Authed & Signal) =>
    apiRequest<AlertOut>("/alerts", { ...o, method: "POST", body }),
  updateAlert: (alertId: string, body: AlertUpdate, o: Authed & Signal) =>
    apiRequest<AlertOut>(`/alerts/${encodeURIComponent(alertId)}`, { ...o, method: "PATCH", body }),
  alertAttempts: (alertId: string, o: Authed & Signal) =>
    apiRequest<NotificationAttemptOut[]>(`/alerts/${encodeURIComponent(alertId)}/attempts`, o),
  advisories: (p: { regionId?: string; since?: string; limit?: number } = {}, o: Signal = {}) =>
    apiRequest<AdvisoryOut[]>("/advisories", {
      ...o,
      query: { region_id: p.regionId, since: p.since, limit: p.limit },
    }),

  analytics: (p: { days?: number; regionId?: string } = {}, o: Signal = {}) =>
    apiRequest<AnalyticsOut>("/analytics", {
      ...o,
      query: { days: p.days ?? 30, region_id: p.regionId },
    }),

  /** Part 14 R2 (M3): observed history + stored predictions for one place. */
  placeAnalytics: (regionId: string, o: Signal = {}) =>
    apiRequest<PlaceAnalyticsOut>("/analytics/place", { ...o, query: { region_id: regionId } }),
  placesAnalytics: (o: Signal = {}) => apiRequest<PlacesAnalyticsOut>("/analytics/places", o),
  /** The deployed model's held-out metrics, as recorded in MongoDB. */
  model: (o: Signal = {}) => apiRequest<ModelPerformance>("/analytics/model", o),

  login: (body: { username: string; password: string }) =>
    apiRequest<TokenOut>("/auth/login", { method: "POST", body, auth: false }),
  /** Revoke the session's token server-side (Part 15 R2). */
  logout: (o: Authed & Signal) =>
    apiRequest<{ signed_out: boolean }>("/auth/logout", { ...o, method: "POST" }),
  me: (o: Authed & Signal) => apiRequest<UserOut>("/auth/me", o),
};
