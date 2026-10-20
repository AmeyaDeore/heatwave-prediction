/**
 * Startup work that needs MongoDB and the ML service (Part 08 R2.4): apply or check
 * migrations, mirror config/regions.yaml into `places`, and record the ML service's model in
 * `model_metadata`. Kept apart from main.ts so tests and the CLIs run the same steps.
 */
import bcrypt from "bcryptjs";
import { DEFAULT_BCRYPT_COST, hashPassword } from "./auth/service.js";
import type { Catalog } from "./catalog.js";
import type { AppEnv } from "./config.js";
import type { Database } from "./db.js";
import { applyMigrations, migrationStatus, MigrationError } from "./db/migrations.js";
import type { Store } from "./db/store.js";
import type { UserStore } from "./db/users.js";
import { errorFields, type Logger } from "./logger.js";
import type { MlService } from "./ml/client.js";

/**
 * local/test: apply pending migrations. staging/production: refuse while any is pending,
 * because migrating there is a deliberate, backed-up step (`npm run db:migrate`).
 */
export async function prepareDatabase(
  appEnv: AppEnv,
  database: Database,
  store: Store,
  catalog: Catalog,
  logger: Logger,
): Promise<void> {
  const db = await database.native();
  if (appEnv === "local" || appEnv === "test") {
    const applied = await applyMigrations(db);
    if (applied.length) logger.info("database migrated", { applied });
  } else {
    const { pending } = await migrationStatus(db);
    if (pending.length) {
      throw new MigrationError(
        `Database has pending migrations ${JSON.stringify(pending)}. Run \`npm run db:migrate\` first.`,
      );
    }
  }
  const upserted = await store.upsertPlaces(catalog.places);
  logger.info("places mirrored from config/regions.yaml", { places: upserted });
}

/** Record the model the ML service has loaded. Returns false if the service is unreachable. */
export async function recordModel(ml: MlService, store: Store, logger: Logger): Promise<boolean> {
  try {
    const model = await ml.model();
    if (await store.recordModel(model)) {
      logger.info("model recorded", {
        model_version: model.model_version,
        explainer_id: model.explainer_id,
      });
    }
    return true;
  } catch (error) {
    logger.warning("could not record the ML service's model yet", errorFields(error));
    return false;
  }
}

/**
 * local/test: seed one demo official (DEMO_USER_USERNAME / DEMO_USER_PASSWORD), as the FastAPI
 * service does. Anywhere else: no default account exists, and a copied local database cannot
 * keep a known password working, so the demo account is deactivated if present.
 */
export async function seedDemoUser(
  appEnv: AppEnv,
  users: UserStore,
  demo: { username: string; password: string },
  logger: Logger,
  bcryptCost = DEFAULT_BCRYPT_COST,
): Promise<void> {
  if (appEnv === "local" || appEnv === "test") {
    const existing = await users.byUsername(demo.username);
    if (existing?.active && (await bcrypt.compare(demo.password, existing.password_hash))) return;
    await users.upsert({
      id: "user_demo",
      username: demo.username,
      display_name: "Demo Official",
      password_hash: await hashPassword(demo.password, bcryptCost),
    });
    logger.info("demo official seeded (local/test only)", { username: demo.username });
  } else if (await users.setActive(demo.username, false)) {
    logger.warning("demo official deactivated: it must not exist outside local/test", {
      username: demo.username,
    });
  }
}
