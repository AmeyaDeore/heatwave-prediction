/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL?: string;
  readonly VITE_DEFAULT_REGION?: string;
  readonly VITE_DASHBOARD_POLL_INTERVAL_MS?: string;
  readonly VITE_INLAND_MODEL_VALIDATED?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
