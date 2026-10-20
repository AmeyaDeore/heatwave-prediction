/**
 * `npm run db:migrate`: apply pending MongoDB migrations (Part 08 R2.4). This is the explicit
 * step staging/production need, run after a backup (`mongodump`). `--status` only reports.
 * Exit codes: 0 done, 1 failure, 2 invalid configuration.
 */
import { ConfigError, loadConfig, redactUri } from "../config.js";
import { Database } from "../db.js";
import { applyMigrations, migrationStatus } from "../db/migrations.js";
import { createLogger } from "../logger.js";

async function main(): Promise<number> {
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
  const database = new Database(config.MONGODB_URI, createLogger({ level: "ERROR" }));
  try {
    const db = await database.native();
    const before = await migrationStatus(db);
    console.log(`Database ${redactUri(config.MONGODB_URI)}`);
    console.log(`  version : ${before.current}`);
    console.log(`  pending : ${before.pending.length ? before.pending.join(", ") : "none"}`);
    if (process.argv.includes("--status")) return 0;
    const applied = await applyMigrations(db);
    console.log(`  applied : ${applied.length ? applied.join(", ") : "nothing to do"}`);
    return 0;
  } catch (error) {
    console.error(`Migration failed: ${error instanceof Error ? error.message : String(error)}`);
    return 1;
  } finally {
    await database.close();
  }
}

process.exitCode = await main();
