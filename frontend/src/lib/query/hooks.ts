/**
 * Data hooks, one per backend read/write, each carrying its refresh policy (./policy.ts).
 * Pages (Parts 11–14) use these and nothing lower: no page calls fetch, picks a query key, or
 * sets its own polling interval.
 */
import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
  type QueryClient,
} from "@tanstack/react-query";
import { api } from "@/lib/api/endpoints";
import type {
  AlertCreate,
  AlertOut,
  AlertStatus,
  AlertUpdate,
  PredictionOut,
} from "@/lib/api/types";
import { useSession } from "@/state/session-context";
import { queryKeys } from "./keys";
import { DELIVERY_POLL_INTERVAL_MS, REFRESH_POLICY } from "./policy";

// --- Reference data ------------------------------------------------------------------------

export function useAlertChannels() {
  return useQuery({
    queryKey: queryKeys.alertChannels(),
    queryFn: ({ signal }) => api.alertChannels({ signal }),
    ...REFRESH_POLICY.reference,
  });
}

/** Model + weather readiness; the nav shell shows a warning when weather data is stale. */
export function useReadiness() {
  return useQuery({
    queryKey: queryKeys.readiness(),
    queryFn: ({ signal }) => api.readiness({ signal }),
    ...REFRESH_POLICY.live,
    // "Not ready" is a 503 with an ok envelope, so it arrives as data ({ready: false}); a real
    // failure here only means the indicator is hidden until the next poll.
    retry: false,
  });
}

// --- Live data (dashboard) -----------------------------------------------------------------

/** Conditions for one region, or all monitored regions with `regionId: null` (regional table). */
export function useWeather(regionId: string | null, leadDays = 0) {
  return useQuery({
    queryKey: queryKeys.weather(regionId, leadDays),
    queryFn: ({ signal }) => api.weather({ regionId: regionId ?? undefined, leadDays }, { signal }),
    ...REFRESH_POLICY.live,
    placeholderData: keepPreviousData,
  });
}

/**
 * The latest stored prediction for a region. `live: true` polls (dashboard); the default is
 * on-demand (Prediction page). A 404 means "none made yet" and surfaces as an empty state.
 */
export function useLatestPrediction(
  regionId: string,
  options: { leadDays?: number; live?: boolean } = {},
) {
  const { leadDays = 0, live = false } = options;
  return useQuery({
    queryKey: queryKeys.latestPrediction(regionId, leadDays),
    queryFn: ({ signal }) => api.latestPrediction({ regionId, leadDays }, { signal }),
    ...(live ? REFRESH_POLICY.live : REFRESH_POLICY.onDemand),
  });
}

/** The newest stored prediction for every place at one lead (map, table, metric cards). Live. */
export function useLatestByRegion(leadDays: number, division: string | null = null) {
  return useQuery({
    queryKey: queryKeys.latestByRegion(leadDays, division),
    queryFn: ({ signal }) =>
      api.latestByRegion({ leadDays, division: division ?? undefined }, { signal }),
    ...REFRESH_POLICY.live,
    placeholderData: keepPreviousData,
  });
}

/** "Score places not yet scored on the current forecast" (Part 11 R2.3). Never automatic. */
export function useScoreMissing() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => api.scoreBatch({ only_missing: true }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: queryKeys.predictions() });
      void client.invalidateQueries({ queryKey: [...queryKeys.all, "analytics"] });
    },
  });
}

export function usePrediction(predictionId: string | null) {
  return useQuery({
    queryKey: queryKeys.prediction(predictionId ?? ""),
    queryFn: ({ signal }) => api.prediction(predictionId ?? "", { signal }),
    enabled: predictionId !== null,
    ...REFRESH_POLICY.reference, // A stored prediction never changes.
  });
}

function storePrediction(client: QueryClient, prediction: PredictionOut) {
  const { region, forecast_window: window } = prediction;
  client.setQueryData(queryKeys.latestPrediction(region.id, window.lead_days), prediction);
  client.setQueryData(queryKeys.prediction(prediction.prediction_id), prediction);
}

/** Explicit "Recompute" (POST /predict). The result becomes the latest stored prediction. */
export function useRecomputePrediction() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (p: { regionId: string; leadDays?: number }) => api.predict(p),
    onSuccess: (prediction) => {
      storePrediction(client, prediction);
      void client.invalidateQueries({ queryKey: [...queryKeys.all, "analytics"] });
    },
  });
}

// --- Alerts --------------------------------------------------------------------------------

export function useAlerts(
  filters: { status?: AlertStatus; regionId?: string; limit?: number; offset?: number } = {},
) {
  return useQuery({
    queryKey: queryKeys.alerts(filters),
    queryFn: ({ signal }) => api.alerts(filters, { signal }),
    ...REFRESH_POLICY.list,
    placeholderData: keepPreviousData,
  });
}

/** Whether an alert's delivery is still in flight (Part 09: poll while pending > 0). */
export function isDeliveryInFlight(alert: AlertOut | undefined): boolean {
  return alert?.status === "ISSUED" && alert.delivery_summary.pending > 0;
}

/** One alert. Polls every 3 s while any channel is PENDING, and stops by itself afterwards. */
export function useAlert(alertId: string | null) {
  return useQuery({
    queryKey: queryKeys.alert(alertId ?? ""),
    queryFn: ({ signal }) => api.alert(alertId ?? "", { signal }),
    enabled: alertId !== null,
    ...REFRESH_POLICY.list,
    refetchInterval: (query) =>
      isDeliveryInFlight(query.state.data) ? DELIVERY_POLL_INTERVAL_MS : false,
  });
}

export function useAlertAttempts(alertId: string | null) {
  const { withToken, isAuthenticated } = useSession();
  return useQuery({
    queryKey: queryKeys.alertAttempts(alertId ?? ""),
    queryFn: ({ signal }) =>
      withToken((token) => api.alertAttempts(alertId ?? "", { token, signal })),
    enabled: alertId !== null && isAuthenticated,
    ...REFRESH_POLICY.list,
  });
}

function storeAlert(client: QueryClient, alert: AlertOut) {
  client.setQueryData(queryKeys.alert(alert.alert_id), alert);
  void client.invalidateQueries({ queryKey: [...queryKeys.alertsRoot(), "list"] });
}

/** Create an alert (protected). Pass a client_request_id generated once per form. */
export function useCreateAlert() {
  const client = useQueryClient();
  const { withToken } = useSession();
  return useMutation({
    mutationFn: (body: AlertCreate) => withToken((token) => api.createAlert(body, { token })),
    onSuccess: (alert) => storeAlert(client, alert),
  });
}

/** Edit or move an alert along DRAFT → READY → ISSUED (protected). */
export function useUpdateAlert() {
  const client = useQueryClient();
  const { withToken } = useSession();
  return useMutation({
    mutationFn: ({ alertId, changes }: { alertId: string; changes: AlertUpdate }) =>
      withToken((token) => api.updateAlert(alertId, changes, { token })),
    onSuccess: (alert) => storeAlert(client, alert),
  });
}

// --- Analytics -----------------------------------------------------------------------------

export function useAnalytics(days: number, regionId: string | null) {
  return useQuery({
    queryKey: queryKeys.analytics(days, regionId),
    queryFn: ({ signal }) => api.analytics({ days, regionId: regionId ?? undefined }, { signal }),
    ...REFRESH_POLICY.historical,
    placeholderData: keepPreviousData,
  });
}

// --- Place analysis (Part 14 R2, M3) ----------------------------------------------------------

export function usePlaceAnalytics(regionId: string) {
  return useQuery({
    queryKey: queryKeys.placeAnalytics(regionId),
    queryFn: ({ signal }) => api.placeAnalytics(regionId, { signal }),
    ...REFRESH_POLICY.historical,
    placeholderData: keepPreviousData,
  });
}

export function usePlacesAnalytics() {
  return useQuery({
    queryKey: queryKeys.placesAnalytics(),
    queryFn: ({ signal }) => api.placesAnalytics({ signal }),
    ...REFRESH_POLICY.historical,
  });
}

export function useModelMetadata() {
  return useQuery({
    queryKey: queryKeys.model(),
    queryFn: ({ signal }) => api.model({ signal }),
    ...REFRESH_POLICY.reference,
  });
}
