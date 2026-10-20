/**
 * `npm run import-history [-- <csv>]`: load the observed history into MongoDB `observed_history`
 * (Part 14 R2). The CSV is written by `heatwave-prepare observed` (default
 * data/processed/observed_dataset.csv): real IMD Tmax with NASA POWER context, labelled in
 * Python by IMD-HW-DAILY-v1. This command never relabels or fills anything. Idempotent: a
 * re-run updates rows in place (unique per place and day).
 * Exit codes: 0 done, 1 failure, 2 configuration or input error.
 */
import { createReadStream, existsSync } from "node:fs";
import { createInterface } from "node:readline";
import { prepareDatabase } from "../bootstrap.js";
import { Catalog, loadPlaces } from "../catalog.js";
import { ConfigError, loadConfig, repoPath } from "../config.js";
import { Database } from "../db.js";
import { Store } from "../db/store.js";
import { createLogger } from "../logger.js";

const BATCH = 5000;
const NUMERIC = [
  "tmax_c",
  "normal_tmax_c",
  "rh_pct",
  "wind_ms",
  "solar_mj_m2",
  "precip_mm",
  "temp_deviation_c",
];

async function main(argv: string[]): Promise<number> {
  let config;
  try {
    config = loadConfig();
  } catch (error) {
    if (error instanceof ConfigError) {
      console.error(error.message);
      return 2;
    }
    throw error;
  }
  const path = repoPath(argv[0] ?? "data/processed/observed_dataset.csv");
  if (!existsSync(path)) {
    console.error(`No file at ${path}. Build it first: heatwave-prepare observed`);
    return 2;
  }
  const catalog = new Catalog(loadPlaces(repoPath(config.MONITORED_REGIONS_FILE)));
  const logger = createLogger({ level: "WARNING" });
  const database = new Database(config.MONGODB_URI, logger);
  try {
    await prepareDatabase(
      config.APP_ENV,
      database,
      new Store(() => database.native()),
      catalog,
      logger,
    );
    const collection = (await database.native()).collection("observed_history");
    const lines = createInterface({ input: createReadStream(path, "utf8"), crlfDelay: Infinity });
    let header: string[] | null = null;
    let batch: object[] = [];
    let rows = 0;
    const unknown = new Set<string>();
    const flush = async () => {
      if (batch.length) await collection.bulkWrite(batch as never[], { ordered: false });
      batch = [];
    };
    for await (const line of lines) {
      if (!line.trim()) continue;
      const cells = line.split(",");
      if (!header) {
        header = cells;
        continue;
      }
      const row = Object.fromEntries(header.map((h, i) => [h, cells[i] ?? ""]));
      if (!catalog.has(row.region_id!)) {
        unknown.add(row.region_id!);
        continue;
      }
      const doc: Record<string, unknown> = {
        region_id: row.region_id,
        date: row.date,
        year: Number(row.date!.slice(0, 4)),
        month: Number(row.date!.slice(5, 7)),
        risk_class: row.risk_class,
      };
      for (const key of NUMERIC)
        doc[key] = row[key] === "" || row[key] === undefined ? null : Number(row[key]);
      batch.push({
        replaceOne: {
          filter: { region_id: doc.region_id, date: doc.date },
          replacement: doc,
          upsert: true,
        },
      });
      rows += 1;
      if (batch.length >= BATCH) await flush();
    }
    await flush();
    if (unknown.size) {
      console.error(`Skipped places not in regions.yaml: ${[...unknown].join(", ")}`);
      return 2;
    }
    const total = await collection.countDocuments();
    const places = (await collection.distinct("region_id")).length;
    console.log(`Imported ${rows} observed place-days from ${path}`);
    console.log(`  observed_history now: ${total} rows, ${places} places`);
    return 0;
  } catch (error) {
    console.error(`Import failed: ${error instanceof Error ? error.message : String(error)}`);
    return 1;
  } finally {
    await database.close();
  }
}

process.exitCode = await main(process.argv.slice(2));
