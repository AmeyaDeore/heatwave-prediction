import { describe, expect, it } from "vitest";
import { ConfigError, databaseName, loadConfig, PLACEHOLDER_SECRET, redactUri } from "./config.js";

const STRONG = "x".repeat(48);

function problems(env: NodeJS.ProcessEnv): string[] {
  try {
    loadConfig(env);
  } catch (error) {
    if (error instanceof ConfigError) return error.problems;
    throw error;
  }
  return [];
}

describe("loadConfig", () => {
  it("has working local defaults", () => {
    const config = loadConfig({});
    expect(config.APP_ENV).toBe("local");
    expect(config.PORT).toBe(4000);
    expect(config.MONGODB_URI).toBe("mongodb://127.0.0.1:27017/heatwave_local");
    expect(config.mongodbDatabase).toBe("heatwave_local");
    expect(config.ML_SERVICE_URL).toBe("http://localhost:8000");
    expect(config.CORS_ALLOWED_ORIGINS).toEqual(["http://localhost:5173"]);
    expect(config.JWT_TTL_MINUTES).toBe(60);
  });

  it("treats empty values as unset, like a blank line in .env", () => {
    expect(loadConfig({ PORT: "", MONGODB_URI: "" }).PORT).toBe(4000);
  });

  it("parses lists and numbers", () => {
    const config = loadConfig({
      PORT: "4100",
      CORS_ALLOWED_ORIGINS: "http://localhost:5173, https://heat.example.org",
    });
    expect(config.PORT).toBe(4100);
    expect(config.CORS_ALLOWED_ORIGINS).toEqual([
      "http://localhost:5173",
      "https://heat.example.org",
    ]);
  });

  it.each(["staging", "production"])("refuses placeholder secrets when APP_ENV=%s", (env) => {
    const found = problems({ APP_ENV: env });
    expect(found.some((p) => p.startsWith("JWT_SECRET:"))).toBe(true);
    expect(found.some((p) => p.startsWith("ML_SERVICE_TOKEN:"))).toBe(true);
  });

  it("refuses short secrets outside local/test", () => {
    const found = problems({
      APP_ENV: "production",
      JWT_SECRET: "short", // pragma: allowlist secret
      ML_SERVICE_TOKEN: STRONG,
    });
    expect(found).toHaveLength(1);
    expect(found[0]).toMatch(/^JWT_SECRET:/);
  });

  it("accepts real secrets outside local/test", () => {
    const config = loadConfig({
      APP_ENV: "production",
      JWT_SECRET: STRONG,
      ML_SERVICE_TOKEN: STRONG,
    });
    expect(config.APP_ENV).toBe("production");
  });

  it("allows the placeholder in local and test", () => {
    expect(loadConfig({ APP_ENV: "test" }).JWT_SECRET).toBe(PLACEHOLDER_SECRET);
  });

  it.each([
    ["MONGODB_URI", "postgres://localhost/heatwave"],
    ["MONGODB_URI", "mongodb://127.0.0.1:27017"],
    ["MONGODB_URI", "mongodb://127.0.0.1:27017/"],
    ["PORT", "0"],
    ["PORT", "http"],
    ["APP_ENV", "dev"],
    ["LOG_LEVEL", "verbose"],
    ["JWT_TTL_MINUTES", "1"],
    ["ML_SERVICE_URL", "ftp://ml"],
    ["CORS_ALLOWED_ORIGINS", "localhost:5173"],
    ["CORS_ALLOWED_ORIGINS", "http://localhost:5173/path"],
  ])("rejects %s=%s", (key, value) => {
    const found = problems({ [key]: value });
    expect(found.some((p) => p.startsWith(`${key}:`))).toBe(true);
  });

  it("never puts a value into its error message", () => {
    const secret = "mongodb://admin:hunter2-very-secret@db.example.org"; // pragma: allowlist secret
    const found = problems({ MONGODB_URI: secret, APP_ENV: "production" });
    expect(found.join("\n")).not.toContain("hunter2");
  });
});

describe("URI helpers", () => {
  it("reads the database name from the path", () => {
    expect(databaseName("mongodb://h:27017/heatwave_local?retryWrites=true")).toBe(
      "heatwave_local",
    );
    expect(databaseName("mongodb+srv://u:p@cluster.example.net/heatwave_prod")).toBe(
      "heatwave_prod",
    );
    expect(databaseName("mongodb://h:27017")).toBeNull();
  });

  it("redacts credentials but keeps host and database", () => {
    // pragma: allowlist nextline secret
    expect(redactUri("mongodb+srv://user:pass@cluster.example.net/heatwave")).toBe(
      "mongodb+srv://***@cluster.example.net/heatwave",
    );
    expect(redactUri("mongodb://127.0.0.1:27017/heatwave_local")).toBe(
      "mongodb://127.0.0.1:27017/heatwave_local",
    );
  });
});
