/**
 * Build-time configuration (frontend/.env.example). Everything here is public: it is compiled
 * into the bundle, so it must never hold a secret.
 */

function readInterval(raw: string | undefined, fallback: number): number {
  const parsed = Number(raw);
  // Polling faster than every 15 s adds load without any visible gain (weather updates hourly).
  return Number.isFinite(parsed) && parsed >= 15_000 ? parsed : fallback;
}

const apiOrigin = (import.meta.env.VITE_API_BASE_URL ?? "http://localhost:4000").replace(
  /\/+$/,
  "",
);

export const env = {
  /** Origin of the Node.js application API (Revision 2); every route is under /api/v1. */
  apiOrigin,
  apiBaseUrl: `${apiOrigin}/api/v1`,
  defaultRegionId: import.meta.env.VITE_DEFAULT_REGION || "mumbai",
  dashboardPollIntervalMs: readInterval(import.meta.env.VITE_DASHBOARD_POLL_INTERVAL_MS, 60_000),
  /**
   * Whether the production model has been validated on inland (plains-zone) places. False until
   * Revision 2 step 10 promotes a model trained and evaluated on the Maharashtra data; until
   * then the map and analysis caveat inland predictions (Part 11 R2.1).
   */
  inlandModelValidated: import.meta.env.VITE_INLAND_MODEL_VALIDATED === "true",
} as const;
