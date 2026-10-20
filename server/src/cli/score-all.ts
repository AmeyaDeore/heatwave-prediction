/**
 * `npm run score-all`: score every monitored place for today + the next 3 days through the ML
 * service and store the predictions (Part 11 R2 decision: a seeding CLI as well as the
 * dashboard's "score places without a prediction" button). The 6-hourly refresh runs it
 * (Part 02 R2.3b). `--only-missing` skips pairs already scored on the current forecast issue.
 * Exit codes: 0 done, 1 failure, 2 invalid configuration.
 */
import { prepareDatabase, recordModel } from "../bootstrap.js";
import { Catalog, CatalogError, loadPlaces } from "../catalog.js";
import { ConfigError, loadConfig, repoPath } from "../config.js";
import { Database } from "../db.js";
import { Store } from "../db/store.js";
import { createLogger } from "../logger.js";
import { HttpMlClient } from "../ml/client.js";
import { PredictionService } from "../services/predictions.js";

async function main(): Promise<number> {
  let config;
  let catalog;
  try {
    config = loadConfig();
    catalog = new Catalog(loadPlaces(repoPath(config.MONITORED_REGIONS_FILE)));
  } catch (error) {
    if (error instanceof ConfigError || error instanceof CatalogError) {
      console.error(error.message);
      return 2;
    }
    throw error;
  }
  const logger = createLogger({ level: "WARNING" });
  const database = new Database(config.MONGODB_URI, logger);
  const store = new Store(() => database.native());
  const ml = new HttpMlClient(
    config.ML_SERVICE_URL,
    config.ML_SERVICE_TOKEN,
    config.ML_SERVICE_TIMEOUT_MS,
  );
  try {
    await prepareDatabase(config.APP_ENV, database, store, catalog, logger);
    await recordModel(ml, store, logger);
    const started = Date.now();
    const result = await new PredictionService(catalog, ml, store).scoreBatch({
      only_missing: process.argv.includes("--only-missing"),
    });
    const classes: Record<string, number> = {};
    for (const p of result.predictions) classes[p.risk_class] = (classes[p.risk_class] ?? 0) + 1;
    console.log(
      `Scored ${result.scored} place x lead pairs (${catalog.places.length} places), ` +
        `skipped ${result.skipped}, in ${Date.now() - started} ms`,
    );
    console.log(`  risk classes: ${JSON.stringify(classes)}`);
    return 0;
  } catch (error) {
    console.error(`Scoring failed: ${error instanceof Error ? error.message : String(error)}`);
    return 1;
  } finally {
    await database.close();
  }
}

process.exitCode = await main();
