/**
 * Settings from environment variables (server/.env.example; inventory in
 * docs/configuration-and-secrets.md). Parsed once at startup. A bad value stops the process
 * with a message that names the variable and the rule, never the value, so a mistyped secret
 * cannot end up in a log.
 *
 * Variables used by later Revision 2 steps (JWT_*, ML_SERVICE_*, CORS_ALLOWED_ORIGINS) are
 * validated now, so the placeholder-secret rule is enforced from the first deployment.
 */
import { isAbsolute, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { z } from "zod";

export const APP_ENVS = ["local", "test", "staging", "production"] as const;
export type AppEnv = (typeof APP_ENVS)[number];
export const LOG_LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR"] as const;
export type LogLevel = (typeof LOG_LEVELS)[number];

/** The committed placeholder for every secret; accepted only in local and test. */
export const PLACEHOLDER_SECRET = "change-me-local-only"; // pragma: allowlist secret
const MIN_SECRET_LENGTH = 32;

const origin = z.string().refine((value) => {
  try {
    const url = new URL(value);
    return (url.protocol === "http:" || url.protocol === "https:") && url.origin === value;
  } catch {
    return false;
  }
}, "must be an origin such as http://localhost:5173 (scheme, host, optional port; no path)");

const schema = z.object({
  APP_ENV: z.enum(APP_ENVS).default("local"),
  LOG_LEVEL: z.enum(LOG_LEVELS).default("INFO"),
  PORT: z.coerce.number().int().min(1).max(65_535).default(4000),
  MONGODB_URI: z
    .string()
    .default("mongodb://127.0.0.1:27017/heatwave_local")
    .refine(
      (value) => /^mongodb(\+srv)?:\/\//.test(value),
      "must start with mongodb:// or mongodb+srv://",
    )
    .refine(
      (value) => databaseName(value) !== null,
      "must name the database in its path, e.g. mongodb://127.0.0.1:27017/heatwave_local",
    ),
  JWT_SECRET: z.string().min(1).default(PLACEHOLDER_SECRET),
  JWT_TTL_MINUTES: z.coerce.number().int().min(5).max(1440).default(60),
  ML_SERVICE_URL: z.url({ protocol: /^https?$/ }).default("http://localhost:8000"),
  ML_SERVICE_TOKEN: z.string().min(1).default(PLACEHOLDER_SECRET),
  CORS_ALLOWED_ORIGINS: z
    .string()
    .default("http://localhost:5173")
    .transform((raw) =>
      raw
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean),
    )
    .pipe(z.array(origin).min(1, "must list at least one origin")),
  // Shared config (config/, read by the Python services too). Relative to the repository root.
  MONITORED_REGIONS_FILE: z.string().default("config/regions.yaml"),
  ML_SERVICE_TIMEOUT_MS: z.coerce.number().int().min(1000).max(120_000).default(30_000),
  // Public rate limits, per client IP per minute (the FastAPI defaults, docs/api §1).
  RATE_LIMIT_PREDICT_PER_MINUTE: z.coerce.number().int().min(1).max(10_000).default(30),
  RATE_LIMIT_ALERTS_PER_MINUTE: z.coerce.number().int().min(1).max(10_000).default(20),
  ALERT_CHANNELS_FILE: z.string().default("config/alert_channels.yaml"),
  // Login (Part 15 R2): per-IP limit, plus a lock on a username after repeated failures.
  RATE_LIMIT_LOGIN_PER_MINUTE: z.coerce.number().int().min(1).max(1000).default(10),
  LOGIN_LOCKOUT_FAILURES: z.coerce.number().int().min(3).max(100).default(10),
  LOGIN_LOCKOUT_MINUTES: z.coerce.number().int().min(1).max(1440).default(15),
  // local/test only: one demo official, as the FastAPI service seeds (never in staging/production).
  DEMO_USER_USERNAME: z.string().min(3).max(64).default("official"),
  DEMO_USER_PASSWORD: z.string().min(8).max(200).default("demo-official-local"), // pragma: allowlist secret
});

export type Config = z.output<typeof schema> & { mongodbDatabase: string };

/** The repository root: server/ is one level below it, wherever the process is started. */
export const REPO_ROOT = fileURLToPath(new URL("../../", import.meta.url));

/** Resolve a config path the way the Python services do: relative to the repository root. */
export function repoPath(value: string): string {
  return isAbsolute(value) ? value : resolve(REPO_ROOT, value);
}

export class ConfigError extends Error {
  constructor(readonly problems: string[]) {
    super(`Invalid configuration:\n${problems.map((p) => `  - ${p}`).join("\n")}`);
    this.name = "ConfigError";
  }
}

/** The database named in a MongoDB URI's path, or null if there is none. */
export function databaseName(uri: string): string | null {
  const match = /^mongodb(?:\+srv)?:\/\/[^/]+\/([^?]+)/.exec(uri);
  const name = match?.[1] ? decodeURIComponent(match[1]) : "";
  return /^[A-Za-z0-9_-]{1,63}$/.test(name) ? name : null;
}

/** A URI safe to log: credentials replaced, host and database kept. */
export function redactUri(uri: string): string {
  return uri.replace(/^(mongodb(?:\+srv)?:\/\/)[^@/]+@/, "$1***@");
}

export function loadConfig(env: NodeJS.ProcessEnv = process.env): Config {
  // Empty strings count as unset, the way an .env template with a blank value reads.
  const present = Object.fromEntries(
    Object.keys(schema.shape)
      .map((key) => [key, env[key]] as const)
      .filter(([, value]) => value !== undefined && value !== ""),
  );
  const parsed = schema.safeParse(present);
  if (!parsed.success) {
    throw new ConfigError(
      // Name the variable only (not "CORS_ALLOWED_ORIGINS.0"): that is what the operator edits.
      parsed.error.issues.map((issue) => `${String(issue.path[0] ?? "config")}: ${issue.message}`),
    );
  }

  const config = parsed.data;
  const problems: string[] = [];
  if (config.APP_ENV !== "local" && config.APP_ENV !== "test") {
    for (const key of ["JWT_SECRET", "ML_SERVICE_TOKEN"] as const) {
      if (config[key] === PLACEHOLDER_SECRET || config[key].length < MIN_SECRET_LENGTH) {
        problems.push(
          `${key}: the local placeholder or a value under ${MIN_SECRET_LENGTH} characters ` +
            `is not allowed when APP_ENV=${config.APP_ENV}`,
        );
      }
    }
  }
  if (problems.length > 0) throw new ConfigError(problems);

  return { ...config, mongodbDatabase: databaseName(config.MONGODB_URI) as string };
}
