/**
 * Query keys, built in one place so invalidation can target a family ("every alert query")
 * without guessing at key shapes. Region-scoped keys include the region id, so switching
 * region switches cache entries instead of refetching into the same one.
 */
import type { AlertStatus } from "@/lib/api/types";

export const queryKeys = {
  all: ["api"] as const,
  regions: () => [...queryKeys.all, "regions"] as const,
  alertChannels: () => [...queryKeys.all, "alert-channels"] as const,
  readiness: () => [...queryKeys.all, "readiness"] as const,
  weather: (regionId: string | null, leadDays = 0) =>
    [...queryKeys.all, "weather", { regionId, leadDays }] as const,
  predictions: () => [...queryKeys.all, "predictions"] as const,
  latestPrediction: (regionId: string, leadDays = 0) =>
    [...queryKeys.predictions(), "latest", { regionId, leadDays }] as const,
  prediction: (predictionId: string) => [...queryKeys.predictions(), "id", predictionId] as const,
  latestByRegion: (leadDays: number, division: string | null) =>
    [...queryKeys.predictions(), "latest-by-region", { leadDays, division }] as const,
  alertsRoot: () => [...queryKeys.all, "alerts"] as const,
  alerts: (filters: { status?: AlertStatus; regionId?: string; limit?: number; offset?: number }) =>
    [...queryKeys.alertsRoot(), "list", filters] as const,
  alert: (alertId: string) => [...queryKeys.alertsRoot(), "id", alertId] as const,
  alertAttempts: (alertId: string) => [...queryKeys.alertsRoot(), "attempts", alertId] as const,
  placeAnalytics: (regionId: string) => [...queryKeys.all, "analytics", "place", regionId] as const,
  placesAnalytics: () => [...queryKeys.all, "analytics", "places"] as const,
  model: () => [...queryKeys.all, "analytics", "model"] as const,
  analytics: (days: number, regionId: string | null) =>
    [...queryKeys.all, "analytics", { days, regionId }] as const,
};
