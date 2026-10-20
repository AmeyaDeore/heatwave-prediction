/**
 * `npm run db:check`: is the configured MongoDB reachable? Read-only: it pings, reads the server
 * version and counts the database's collections. It creates and writes nothing.
 * Exit codes: 0 reachable, 1 unreachable, 2 invalid configuration.
 */
import { ConfigError, loadConfig, redactUri } from "../config.js";
import { Database } from "../db.js";
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

  // Connection warnings stay quiet; this command prints its own result.
  const database = new Database(config.MONGODB_URI, createLogger({ level: "ERROR" }));
  try {
    const info = await database.info();
    console.log(`MongoDB reachable at ${redactUri(config.MONGODB_URI)}`);
    console.log(`  server version : ${info.version}`);
    console.log(`  database       : ${info.database} (${info.collections} collections)`);
    return 0;
  } catch (error) {
    console.error(`MongoDB NOT reachable at ${redactUri(config.MONGODB_URI)}`);
    console.error(`  reason: ${error instanceof Error ? error.message : String(error)}`);
    console.error("  Start MongoDB first (docs/local-dev-runbook.md, step 6a).");
    return 1;
  } finally {
    await database.close();
  }
}

process.exitCode = await main();
