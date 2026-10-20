/**
 * The internal ML inference service (FastAPI, SERVICE_ROLE=ml; Part 07 §A). It is the only
 * component that computes features, predictions, SHAP factors and recommended actions. This
 * API never re-derives them: it stores and serves exactly what comes back.
 */
import { ApiError, type ErrorKind } from "../http/envelope.js";

/** A prediction as the ML service returns it (docs/api/README.md, PredictionOut). */
export interface PredictionPayload {
  prediction_id: string;
  created_at: string;
  region: { id: string; [key: string]: unknown };
  forecast_window: {
    valid_date: string;
    lead_days: number;
    issued_at: string;
    horizon_days?: number;
  };
  risk_class: "NORMAL" | "HEATWAVE" | "SEVERE_HEATWAVE";
  explanation: { model_version: string; explainer_id: string; [key: string]: unknown };
  [key: string]: unknown;
}

/** Conditions for one place and lead (docs/api/README.md, WeatherOut). */
export interface WeatherPayload {
  region: { id: string; [key: string]: unknown };
  date: string;
  lead_days: number;
  provenance: { source: string; issued_at: string; age_hours: number; stale: boolean };
  [key: string]: unknown;
}

export interface ModelPayload {
  model_version: string;
  explainer_id: string;
  [key: string]: unknown;
}

export interface MlReadiness {
  ready: boolean;
  model_version?: string;
  explainer_id?: string;
  weather_data?: string;
  weather_issued_at?: string | null;
}

export interface MlService {
  predict(regionId: string, leadDays: number): Promise<PredictionPayload>;
  predictBatch(items: { region_id: string; lead_days: number }[]): Promise<PredictionPayload[]>;
  weather(regionId: string | undefined, leadDays: number): Promise<WeatherPayload[]>;
  model(): Promise<ModelPayload>;
  readiness(): Promise<MlReadiness | null>;
}

const UNAVAILABLE = (detail: string) =>
  new ApiError(
    503,
    "ML_SERVICE_UNAVAILABLE",
    "The prediction service is unavailable. Stored data is still shown; try again shortly.",
    "upstream",
    { reason: detail },
  );

export class HttpMlClient implements MlService {
  constructor(
    private readonly baseUrl: string,
    private readonly token: string,
    private readonly timeoutMs = 30_000,
    private readonly fetchImpl: typeof fetch = fetch,
  ) {}

  predict(regionId: string, leadDays: number) {
    return this.call<PredictionPayload>("POST", "/api/v1/predict", {
      region_id: regionId,
      lead_days: leadDays,
    });
  }

  predictBatch(items: { region_id: string; lead_days: number }[]) {
    return this.call<PredictionPayload[]>("POST", "/api/v1/predict/batch", { items });
  }

  weather(regionId: string | undefined, leadDays: number) {
    const query = new URLSearchParams({ lead_days: String(leadDays) });
    if (regionId) query.set("region_id", regionId);
    return this.call<WeatherPayload[]>("GET", `/api/v1/weather?${query}`);
  }

  model() {
    return this.call<ModelPayload>("GET", "/api/v1/model");
  }

  /** The service's own readiness, or null when it cannot be reached. Never throws. */
  async readiness(): Promise<MlReadiness | null> {
    try {
      const response = await this.send("GET", "/api/v1/health/ready");
      const body = (await response.json()) as { status?: string; data?: MlReadiness };
      return body.status === "ok" && body.data ? body.data : null;
    } catch {
      return null;
    }
  }

  private async send(method: string, path: string, body?: unknown): Promise<Response> {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.timeoutMs);
    try {
      return await this.fetchImpl(`${this.baseUrl.replace(/\/+$/, "")}${path}`, {
        method,
        headers: {
          Accept: "application/json",
          "X-Service-Token": this.token,
          ...(body === undefined ? {} : { "Content-Type": "application/json" }),
        },
        body: body === undefined ? undefined : JSON.stringify(body),
        signal: controller.signal,
      });
    } finally {
      clearTimeout(timer);
    }
  }

  private async call<T>(method: string, path: string, body?: unknown): Promise<T> {
    let response: Response;
    try {
      response = await this.send(method, path, body);
    } catch (error) {
      const timedOut = error instanceof Error && error.name === "AbortError";
      throw UNAVAILABLE(timedOut ? `timeout after ${this.timeoutMs} ms` : "unreachable");
    }

    type Envelope = {
      status?: string;
      data?: T;
      error?: { kind: ErrorKind; code: string; message: string; details: unknown };
    };
    let envelope: Envelope;
    try {
      envelope = (await response.json()) as Envelope;
    } catch {
      throw UNAVAILABLE(`non-JSON response (HTTP ${response.status})`);
    }
    if (envelope.status === "ok" && response.ok) return envelope.data as T;

    const error = envelope.error;
    // Client and upstream errors are about this request (unknown region, missing weather):
    // pass them on unchanged. Anything else means the service itself is not usable.
    if (
      error &&
      (error.kind === "client" || error.kind === "upstream") &&
      response.status !== 401
    ) {
      throw new ApiError(response.status, error.code, error.message, error.kind, error.details);
    }
    throw UNAVAILABLE(
      response.status === 401 ? "service token rejected" : `HTTP ${response.status}`,
    );
  }
}
