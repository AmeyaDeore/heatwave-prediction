/**
 * Revision 2 step 5: login on Node.js + MongoDB (Part 15 R2, teacher's M1). The auth matrix,
 * token lifecycle, logout, brute-force guards, demo seeding and CORS, end to end over HTTP.
 */
import { randomBytes } from "node:crypto";
import jwt from "jsonwebtoken";
import request from "supertest";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { createApp } from "./app.js";
import { AuthService, hashPassword, LoginGuard } from "./auth/service.js";
import { prepareDatabase, seedDemoUser } from "./bootstrap.js";
import { Catalog, loadPlaces } from "./catalog.js";
import { repoPath } from "./config.js";
import { Database } from "./db.js";
import { Store } from "./db/store.js";
import { UserStore } from "./db/users.js";
import { RateLimiter } from "./http/ratelimit.js";
import { createLogger } from "./logger.js";
import { PredictionService } from "./services/predictions.js";
import { FakeMl } from "./test/fake-ml.js";
import { startTestMongo } from "./test/mongo.js";

const quiet = createLogger({ level: "ERROR", write: () => undefined });
const SECRET = "s".repeat(48); // pragma: allowlist secret
const PASSWORD = "correct-horse-battery"; // pragma: allowlist secret
const COST = 4; // bcrypt cost for tests only; production uses 12
const ORIGIN = "http://localhost:5173";
const catalog = new Catalog(loadPlaces(repoPath("config/regions.yaml")));

let mongo: Awaited<ReturnType<typeof startTestMongo>>;
const open: Database[] = [];
beforeAll(async () => {
  mongo = await startTestMongo();
});
afterAll(async () => {
  await Promise.all(open.map((d) => d.close()));
  await mongo?.stop();
});

async function setup(
  options: { loginLimit?: number; lockAfter?: number; ttlMinutes?: number } = {},
) {
  const database = new Database(mongo.uri(`auth_${randomBytes(4).toString("hex")}`), quiet);
  open.push(database);
  const store = new Store(() => database.native());
  const users = new UserStore(() => database.native());
  await prepareDatabase("test", database, store, catalog, quiet);
  await users.upsert({
    username: "asha",
    display_name: "Asha Patil",
    password_hash: await hashPassword(PASSWORD, COST),
  });
  const ml = new FakeMl();
  const auth = new AuthService(
    users,
    SECRET,
    options.ttlMinutes ?? 60,
    new LoginGuard(options.lockAfter ?? 10, 15),
    COST,
  );
  const app = createApp({
    config: { APP_ENV: "test" },
    database,
    logger: quiet,
    ml,
    api: {
      catalog,
      predictions: new PredictionService(catalog, ml, store),
      limiter: new RateLimiter({ predict: 1000, login: options.loginLimit ?? 1000 }),
    },
    auth,
    corsOrigins: [ORIGIN],
  });
  const login = (username = "asha", password = PASSWORD) =>
    request(app).post("/api/v1/auth/login").send({ username, password });
  return { app, users, auth, login };
}

const bearer = (token: string) => ({ Authorization: `Bearer ${token}` });

describe("login", () => {
  it("returns the FastAPI TokenOut shape with a 60-minute expiry", async () => {
    const { login } = await setup();
    const before = Date.now();
    const res = await login();
    expect(res.status).toBe(200);
    expect(res.body.data).toMatchObject({
      token_type: "bearer",
      user: { username: "asha", display_name: "Asha Patil", role: "official" },
    });
    expect(Object.keys(res.body.data.user).sort()).toEqual([
      "display_name",
      "id",
      "role",
      "username",
    ]);
    const minutes = (Date.parse(res.body.data.expires_at) - before) / 60_000;
    expect(minutes).toBeGreaterThan(59);
    expect(minutes).toBeLessThanOrEqual(60.1);
    const claims = jwt.decode(res.body.data.access_token, { complete: true })!;
    expect(claims.header.alg).toBe("HS256");
    expect(Object.keys(claims.payload as object).sort()).toEqual(["exp", "jti", "role", "sub"]);
  });

  it("is case-insensitive on the username", async () => {
    const { login } = await setup();
    expect((await login("  ASHA ")).status).toBe(200);
  });

  it("gives the same answer for a wrong password, an unknown user and a disabled account", async () => {
    const { login, users } = await setup();
    await users.upsert({
      username: "ravi",
      display_name: "Ravi",
      password_hash: await hashPassword(PASSWORD, COST),
    });
    await users.setActive("ravi", false);
    const answers = await Promise.all([
      login("asha", "wrong"),
      login("nobody", PASSWORD),
      login("ravi", PASSWORD),
    ]);
    for (const res of answers) {
      expect(res.status).toBe(401);
      expect(res.body.error).toEqual({
        kind: "client",
        code: "UNAUTHORIZED",
        message: "Incorrect username or password.",
        details: null,
      });
    }
  });

  it("validates the body strictly and never echoes it", async () => {
    const { app } = await setup();
    const res = await request(app)
      .post("/api/v1/auth/login")
      .send({ username: "asha", password: "x", remember: true });
    expect(res.status).toBe(422);
    expect(JSON.stringify(res.body)).not.toContain("asha");
  });

  it("is rate limited per client IP", async () => {
    const { login } = await setup({ loginLimit: 3 });
    const codes = [];
    for (let i = 0; i < 4; i++) codes.push((await login("asha", "wrong")).status);
    expect(codes).toEqual([401, 401, 401, 429]);
  });

  it("locks a username after repeated failures, for unknown names too (no enumeration)", async () => {
    const { login } = await setup({ lockAfter: 3 });
    for (const name of ["asha", "ghost"]) {
      for (let i = 0; i < 3; i++) expect((await login(name, "wrong")).status).toBe(401);
      const locked = await login(name, name === "asha" ? PASSWORD : "anything");
      expect(locked.status).toBe(429);
      expect(locked.body.error.message).toBe("Too many sign-in attempts. Try again later.");
      expect(Number(locked.headers["retry-after"])).toBeGreaterThan(0);
    }
  });

  it("a success clears the failure count", async () => {
    const { login } = await setup({ lockAfter: 3 });
    await login("asha", "wrong");
    await login("asha", "wrong");
    expect((await login()).status).toBe(200);
    await login("asha", "wrong");
    await login("asha", "wrong");
    expect((await login()).status).toBe(200);
  });
});

describe("the auth matrix (Part 15 R2.2)", () => {
  const PROTECTED: [string, string, object?][] = [
    ["get", "/api/v1/regions"],
    ["get", "/api/v1/weather?region_id=pune"],
    ["post", "/api/v1/predict", { region_id: "pune" }],
    ["post", "/api/v1/predictions/batch", {}],
    ["get", "/api/v1/predictions/latest?region_id=pune"],
    ["get", "/api/v1/predictions/latest-by-region"],
    ["get", "/api/v1/predictions/pred_0000000000000000"],
    ["get", "/api/v1/auth/me"],
    ["post", "/api/v1/auth/logout"],
  ];

  it.each(PROTECTED)("%s %s needs a session", async (method, path, body) => {
    const { app } = await setup();
    const req = (request(app) as unknown as Record<string, (p: string) => request.Test>)[method]!(
      path,
    );
    const res = await (body ? req.send(body) : req);
    expect(res.status).toBe(401);
    expect(res.body.error.message).toBe("Sign in to continue.");
  });

  it.each(PROTECTED)("%s %s works with a valid session", async (method, path, body) => {
    const { app, login } = await setup();
    const token = (await login()).body.data.access_token;
    const req = (request(app) as unknown as Record<string, (p: string) => request.Test>)[method]!(
      path,
    ).set(bearer(token));
    const res = await (body ? req.send(body) : req);
    expect(res.status).not.toBe(401);
  });

  it.each(["/health", "/api/v1/health/ready"])("%s stays open for probes", async (path) => {
    const { app } = await setup();
    expect((await request(app).get(path)).status).toBe(200);
  });

  it.each([
    ["no scheme", (t: string) => t],
    ["a tampered signature", (t: string) => t.slice(0, -2) + (t.endsWith("AA") ? "BB" : "AA")],
    [
      "another secret",
      () =>
        jwt.sign({ sub: "user_x", role: "official", jti: "j" }, "other-secret-".repeat(4), {
          algorithm: "HS256",
          expiresIn: 600,
        }),
    ],
    [
      "alg none",
      () => jwt.sign({ sub: "user_x", role: "official", jti: "j" }, "", { algorithm: "none" }),
    ],
  ])("rejects a token with %s", async (_label, make) => {
    const { app, login } = await setup();
    const token = make((await login()).body.data.access_token);
    const header = _label === "no scheme" ? { Authorization: token } : bearer(token);
    expect((await request(app).get("/api/v1/regions").set(header)).status).toBe(401);
  });

  it("rejects an expired token", async () => {
    const { app, auth, users } = await setup();
    const user = (await users.byUsername("asha"))!;
    const old = auth.issue(user, new Date(Date.now() - 2 * 60 * 60_000));
    expect((await request(app).get("/api/v1/regions").set(bearer(old.access_token))).status).toBe(
      401,
    );
  });

  it("rejects the token of an account disabled after sign-in", async () => {
    const { app, login, users } = await setup();
    const token = (await login()).body.data.access_token;
    await users.setActive("asha", false);
    expect((await request(app).get("/api/v1/regions").set(bearer(token))).status).toBe(401);
  });
});

describe("me and logout", () => {
  it("me returns the public user only", async () => {
    const { app, login } = await setup();
    const token = (await login()).body.data.access_token;
    const res = await request(app).get("/api/v1/auth/me").set(bearer(token));
    expect(res.body.data).toEqual({
      id: expect.stringMatching(/^user_/),
      username: "asha",
      display_name: "Asha Patil",
      role: "official",
    });
  });

  it("logout revokes the token; a fresh sign-in works again", async () => {
    const { app, login } = await setup();
    const token = (await login()).body.data.access_token;
    expect((await request(app).post("/api/v1/auth/logout").set(bearer(token))).status).toBe(200);
    expect((await request(app).get("/api/v1/regions").set(bearer(token))).status).toBe(401);
    const again = (await login()).body.data.access_token;
    expect((await request(app).get("/api/v1/regions").set(bearer(again))).status).toBe(200);
  });
});

describe("accounts", () => {
  it("stores only a bcrypt hash; the database refuses a plain password", async () => {
    const { users } = await setup();
    const stored = (await users.byUsername("asha"))!;
    expect(stored.password_hash).toMatch(/^\$2[aby]\$\d{2}\$/);
    expect(stored.password_hash).not.toContain(PASSWORD);
    await expect(
      users.upsert({ username: "plain", display_name: "P", password_hash: PASSWORD }),
    ).rejects.toThrow(/validation/i);
  });

  it("seeds the demo official in local/test and deactivates it elsewhere", async () => {
    const { users, login } = await setup();
    await seedDemoUser(
      "test",
      users,
      { username: "official", password: "demo-official-local" }, // pragma: allowlist secret
      quiet,
      COST,
    );
    expect((await login("official", "demo-official-local")).status).toBe(200);
    await seedDemoUser(
      "production",
      users,
      { username: "official", password: "demo-official-local" }, // pragma: allowlist secret
      quiet,
      COST,
    );
    expect((await users.byUsername("official"))!.active).toBe(false);
    expect((await login("official", "demo-official-local")).status).toBe(401);
  });
});

describe("CORS", () => {
  it("allows the frontend origin with the agreed methods and headers", async () => {
    const { app } = await setup();
    const res = await request(app)
      .options("/api/v1/predict")
      .set("Origin", ORIGIN)
      .set("Access-Control-Request-Method", "POST")
      .set("Access-Control-Request-Headers", "authorization,content-type");
    expect(res.headers["access-control-allow-origin"]).toBe(ORIGIN);
    expect(res.headers["access-control-allow-methods"]).toBe("GET,POST,PATCH,OPTIONS");
    expect(res.headers["access-control-allow-headers"]).toBe(
      "Authorization,Content-Type,X-Request-ID",
    );
  });

  it("does not allow another origin", async () => {
    const { app } = await setup();
    const res = await request(app)
      .options("/api/v1/predict")
      .set("Origin", "https://evil.example")
      .set("Access-Control-Request-Method", "POST");
    expect(res.headers["access-control-allow-origin"]).toBeUndefined();
  });
});

describe("contract: Node's auth responses match docs/api/openapi.json", () => {
  it("TokenOut and UserOut carry exactly the documented fields", async () => {
    const { readFileSync } = await import("node:fs");
    const spec = JSON.parse(readFileSync(repoPath("docs/api/openapi.json"), "utf8"));
    const schemas = spec.components.schemas as Record<
      string,
      { properties: object; required?: string[] }
    >;
    const { app, login } = await setup();
    const token = (await login()).body.data;
    const me = (await request(app).get("/api/v1/auth/me").set(bearer(token.access_token))).body
      .data;
    for (const [name, body] of [
      ["TokenOut", token],
      ["UserOut", me],
      ["UserOut", token.user],
    ] as const) {
      const defined = Object.keys(schemas[name]!.properties).sort();
      expect(Object.keys(body).sort(), name).toEqual(defined);
      for (const field of schemas[name]!.required ?? [])
        expect(body, `${name}.${field}`).toHaveProperty(field);
    }
  });
});
