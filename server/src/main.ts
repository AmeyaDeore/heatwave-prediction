/**
 * Process entry point: `npm run dev` (watch) or `npm start` (built). Loads config and the
 * place catalog, serves HTTP at once, then prepares MongoDB and records the ML service's model
 * in the background, retrying while either is down. Shuts down cleanly on SIGINT/SIGTERM.
 */
import { createApp } from "./app.js";
import { AuthService, LoginGuard } from "./auth/service.js";
import { prepareDatabase, recordModel, seedDemoUser } from "./bootstrap.js";
import { Catalog, CatalogError, loadPlaces } from "./catalog.js";
import { ConfigError, loadConfig, redactUri, repoPath } from "./config.js";
import { Database } from "./db.js";
import { MigrationError } from "./db/migrations.js";
import { Store } from "./db/store.js";
import { UserStore } from "./db/users.js";
import { RateLimiter } from "./http/ratelimit.js";
import { createLogger, errorFields } from "./logger.js";
import { HttpMlClient } from "./ml/client.js";
import { AlertService, loadChannels } from "./services/alerts.js";
import { AnalyticsService } from "./services/analytics.js";
import { PredictionService } from "./services/predictions.js";

const RETRY_MS = 10_000;

function fail(message: string, code: number): never {
  process.stderr.write(`${message}\n`);
  process.exit(code);
}

function main(): void {
  let config;
  let catalog;
  try {
    config = loadConfig();
    catalog = new Catalog(loadPlaces(repoPath(config.MONITORED_REGIONS_FILE)));
  } catch (error) {
    if (error instanceof ConfigError || error instanceof CatalogError) fail(error.message, 2);
    throw error;
  }

  const logger = createLogger({ level: config.LOG_LEVEL });
  const database = new Database(config.MONGODB_URI, logger.child("db"));
  const store = new Store(() => database.native());
  const users = new UserStore(() => database.native());
  const auth = new AuthService(
    users,
    config.JWT_SECRET,
    config.JWT_TTL_MINUTES,
    new LoginGuard(config.LOGIN_LOCKOUT_FAILURES, config.LOGIN_LOCKOUT_MINUTES),
  );
  const ml = new HttpMlClient(
    config.ML_SERVICE_URL,
    config.ML_SERVICE_TOKEN,
    config.ML_SERVICE_TIMEOUT_MS,
  );
  const alerts = new AlertService(
    () => database.native(),
    catalog,
    loadChannels(repoPath(config.ALERT_CHANNELS_FILE)),
    logger.child("alerts"),
  );
  const analytics = new AnalyticsService(() => database.native(), catalog, store);
  const app = createApp({
    config,
    database,
    logger,
    ml,
    api: {
      catalog,
      predictions: new PredictionService(catalog, ml, store),
      alerts,
      analytics,
      limiter: new RateLimiter({
        predict: config.RATE_LIMIT_PREDICT_PER_MINUTE,
        login: config.RATE_LIMIT_LOGIN_PER_MINUTE,
        alerts: config.RATE_LIMIT_ALERTS_PER_MINUTE,
      }),
    },
    auth,
    corsOrigins: config.CORS_ALLOWED_ORIGINS,
  });

  const server = app.listen(config.PORT, () => {
    logger.info("startup complete", {
      env: config.APP_ENV,
      port: config.PORT,
      database: config.mongodbDatabase,
      places: catalog.places.length,
      ml_service: config.ML_SERVICE_URL,
    });
  });
  server.on("error", (error) => {
    logger.error("server failed to start", errorFields(error));
    process.exit(1);
  });

  const timers: NodeJS.Timeout[] = [];
  const prepare = async (): Promise<void> => {
    try {
      await prepareDatabase(config.APP_ENV, database, store, catalog, logger);
      await seedDemoUser(
        config.APP_ENV,
        users,
        { username: config.DEMO_USER_USERNAME, password: config.DEMO_USER_PASSWORD },
        logger,
      );
      const resumed = await alerts.resumePending();
      if (resumed) logger.info("resumed alert deliveries", { alerts: resumed });
    } catch (error) {
      if (error instanceof MigrationError) fail(error.message, 1);
      logger.warning("database not ready; retrying", {
        uri: redactUri(config.MONGODB_URI),
        retry_in_ms: RETRY_MS,
        ...errorFields(error),
      });
      timers.push(setTimeout(() => void prepare(), RETRY_MS).unref());
      return;
    }
    const record = async (): Promise<void> => {
      if (!(await recordModel(ml, store, logger))) {
        timers.push(setTimeout(() => void record(), RETRY_MS * 3).unref());
      }
    };
    await record();
  };
  void prepare();

  let stopping = false;
  const stop = (signal: string) => {
    if (stopping) return;
    stopping = true;
    logger.info("shutting down", { signal });
    timers.forEach(clearTimeout);
    server.close(() => {
      void database.close().finally(() => process.exit(0));
    });
    setTimeout(() => process.exit(1), 10_000).unref();
  };
  process.on("SIGINT", () => stop("SIGINT"));
  process.on("SIGTERM", () => stop("SIGTERM"));
}

main();
