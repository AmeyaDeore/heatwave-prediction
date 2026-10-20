/**
 * The Express application (Part 07 §B): liveness, readiness, the shared request id, access
 * log, 404 and error conventions, and, when its services are passed in, the /api/v1 routes.
 *
 * Built by a factory with its dependencies passed in, so tests run it without a real database
 * or ML service.
 */
import cors from "cors";
import express, { type ErrorRequestHandler, type Express, type RequestHandler } from "express";
import type { AuthService } from "./auth/service.js";
import type { Config } from "./config.js";
import type { DatabaseHealth } from "./db.js";
import { ApiError, sendError, sendOk } from "./http/envelope.js";
import { requestContext } from "./http/request-context.js";
import { authRouter, requireAuth } from "./http/auth-routes.js";
import { apiRouter, type ApiDependencies } from "./http/routes.js";
import { errorFields, type Logger } from "./logger.js";
import type { MlService } from "./ml/client.js";

export interface AppDependencies {
  config: Pick<Config, "APP_ENV">;
  database: DatabaseHealth;
  logger: Logger;
  /** The ML service, for readiness. Optional so the skeleton can run without it. */
  ml?: Pick<MlService, "readiness">;
  /** The /api/v1 application routes (step 4 onward). */
  api?: ApiDependencies;
  /** Login (step 5). When given, every /api/v1 data route requires a valid session. */
  auth?: AuthService;
  /** Browser origins allowed to call the API (CORS_ALLOWED_ORIGINS). */
  corsOrigins?: string[];
}

export function createApp({
  config,
  database,
  logger,
  ml,
  api,
  auth,
  corsOrigins,
}: AppDependencies): Express {
  const app = express();
  app.disable("x-powered-by");
  app.set("trust proxy", false); // Part 18 decides proxy handling; never trust it by default.

  app.use(requestContext(logger.child("access")));
  if (corsOrigins) {
    // The FastAPI service's CORS rules (docs/api §1); any other origin's preflight is refused.
    app.use(
      cors({
        origin: corsOrigins,
        credentials: true,
        methods: ["GET", "POST", "PATCH", "OPTIONS"],
        allowedHeaders: ["Authorization", "Content-Type", "X-Request-ID"],
        exposedHeaders: ["X-Request-ID", "Retry-After"],
        maxAge: 600,
      }),
    );
  }
  app.use(express.json({ limit: "100kb" }));

  /** Liveness only: the process is up. Same shape as the FastAPI service's /health. */
  app.get("/health", (_req, res) => {
    res.json({ status: "ok", env: config.APP_ENV });
  });

  /**
   * Readiness: 503 with an ok envelope when a dependency is down, so a probe can act on the
   * status code alone (the FastAPI convention). Stored reads keep working while the ML
   * service is down; readiness says so instead of hiding it.
   */
  app.get("/api/v1/health/ready", async (_req, res) => {
    const [databaseUp, mlReady] = await Promise.all([database.ping(), ml?.readiness()]);
    const data: Record<string, unknown> = {
      ready: databaseUp,
      database: databaseUp ? "ok" : "unavailable",
    };
    if (ml) {
      data.ml_service = mlReady?.ready ? "ok" : "unavailable";
      data.model_version = mlReady?.model_version ?? null;
      data.explainer_id = mlReady?.explainer_id ?? null;
      data.weather_data = mlReady?.weather_data ?? null;
      data.weather_issued_at = mlReady?.weather_issued_at ?? null;
      data.ready = databaseUp && Boolean(mlReady?.ready);
    }
    sendOk(res, data, data.ready ? 200 : 503);
  });

  if (api) {
    if (auth) {
      app.use("/api/v1", authRouter(auth, api.limiter));
      app.use("/api/v1", requireAuth(auth), apiRouter(api));
    } else {
      app.use("/api/v1", apiRouter(api)); // no auth configured (tests of the routes alone)
    }
  }

  app.use(notFound);
  app.use(errorHandler(logger));
  return app;
}

const MONGO_UNAVAILABLE = new Set([
  "MongooseServerSelectionError", // Mongoose's wrapper when the initial connect fails
  "MongoServerSelectionError",
  "MongoNotConnectedError",
  "MongoNetworkError",
  "MongoNetworkTimeoutError",
  "MongoTopologyClosedError",
]);

function isMongoUnavailable(error: unknown): boolean {
  return error instanceof Error && MONGO_UNAVAILABLE.has(error.name);
}

const notFound: RequestHandler = (req, res) => {
  sendError(res, new ApiError(404, "NOT_FOUND", `No route for ${req.method} ${req.path}.`));
};

/** Unexpected errors become a 500 INTERNAL_ERROR quoting the request id; details go to the log. */
export function errorHandler(logger: Logger): ErrorRequestHandler {
  return (error, req, res, _next) => {
    if (error instanceof ApiError) {
      if (error.kind !== "client") {
        logger.warning(error.message, {
          request_id: res.locals.requestId,
          code: error.code,
          kind: error.kind,
        });
      }
      return sendError(res, error);
    }
    // MongoDB unreachable or dropped: a clear 503, not a 500 (readiness reports it too).
    if (isMongoUnavailable(error)) {
      logger.warning("database unavailable", {
        request_id: res.locals.requestId,
        ...errorFields(error),
      });
      return sendError(
        res,
        new ApiError(
          503,
          "DATABASE_UNAVAILABLE",
          "The database is unavailable. Try again shortly.",
        ),
      );
    }
    // Body-parser and similar client errors carry a 4xx status; never echo their content.
    const status = typeof error?.status === "number" ? error.status : 500;
    if (status >= 400 && status < 500) {
      const code = status === 413 ? "PAYLOAD_TOO_LARGE" : "BAD_REQUEST";
      return sendError(res, new ApiError(status, code, "The request could not be read."));
    }
    logger.error("unhandled error", {
      request_id: res.locals.requestId,
      path: req.path,
      ...errorFields(error),
    });
    sendError(
      res,
      new ApiError(
        500,
        "INTERNAL_ERROR",
        `Something went wrong on our side. Quote request id ${String(res.locals.requestId)}.`,
      ),
    );
  };
}
