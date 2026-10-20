/**
 * Login for Local Authority / Disaster Management Officials (Part 15 R2, teacher's M1).
 *
 *  - Passwords: bcrypt (cost 12 by default). A wrong password and an unknown username give the
 *    same answer and take the same time (an unknown name is checked against a dummy hash).
 *  - Tokens: JWT HS256 (`JWT_SECRET`), claims sub / role / jti / exp, 60 minutes by default, no
 *    silent refresh. The response has the FastAPI service's TokenOut shape, so the Part 10
 *    session code is unchanged.
 *  - Logout revokes the token's jti until it would have expired (`revoked_tokens`, TTL).
 *  - Brute force: a per-IP rate limit on the route, plus this lock on a username after
 *    repeated failures. Failures are counted for every typed name, existing or not, so the
 *    lock reveals nothing about which accounts exist.
 */
import { randomBytes } from "node:crypto";
import bcrypt from "bcryptjs";
import jwt from "jsonwebtoken";
import {
  type UserDoc,
  type UserOut,
  type UserStore,
  normaliseUsername,
  toUserOut,
} from "../db/users.js";
import { ApiError } from "../http/envelope.js";

export const DEFAULT_BCRYPT_COST = 12;
const INVALID = () => new ApiError(401, "UNAUTHORIZED", "Incorrect username or password.");
const SIGN_IN = () => new ApiError(401, "UNAUTHORIZED", "Sign in to continue.");

export function hashPassword(password: string, cost = DEFAULT_BCRYPT_COST): Promise<string> {
  return bcrypt.hash(password, cost);
}

/** Consecutive failures per typed username, per process (like the rate limiter). */
export class LoginGuard {
  private readonly failures = new Map<string, { count: number; lockedUntil: number }>();

  constructor(
    private readonly maxFailures: number,
    private readonly lockMinutes: number,
    private readonly now: () => number = () => Date.now(),
  ) {}

  /** Seconds left on a lock, or 0. */
  lockedFor(username: string): number {
    const entry = this.failures.get(normaliseUsername(username));
    const left = entry ? entry.lockedUntil - this.now() : 0;
    return left > 0 ? Math.ceil(left / 1000) : 0;
  }

  fail(username: string): void {
    const key = normaliseUsername(username);
    const entry = this.failures.get(key) ?? { count: 0, lockedUntil: 0 };
    entry.count += 1;
    if (entry.count >= this.maxFailures) {
      entry.lockedUntil = this.now() + this.lockMinutes * 60_000;
      entry.count = 0;
    }
    this.failures.set(key, entry);
  }

  succeed(username: string): void {
    this.failures.delete(normaliseUsername(username));
  }
}

export interface TokenOut {
  access_token: string;
  token_type: "bearer";
  expires_at: string;
  user: UserOut;
}

export interface AuthenticatedUser extends UserOut {
  jti: string;
  expiresAt: Date;
}

interface Claims {
  sub: string;
  role: string;
  jti: string;
  exp: number;
}

export class AuthService {
  private readonly dummyHash: Promise<string>;

  constructor(
    private readonly users: UserStore,
    private readonly secret: string,
    private readonly ttlMinutes: number,
    private readonly guard: LoginGuard,
    private readonly bcryptCost = DEFAULT_BCRYPT_COST,
  ) {
    this.dummyHash = hashPassword(randomBytes(16).toString("hex"), bcryptCost);
  }

  async login(username: string, password: string, now = new Date()): Promise<TokenOut> {
    const locked = this.guard.lockedFor(username);
    if (locked > 0) {
      throw Object.assign(
        new ApiError(429, "RATE_LIMITED", "Too many sign-in attempts. Try again later.", "client", {
          retry_after_seconds: locked,
        }),
        { retryAfter: locked },
      );
    }
    const user = await this.users.byUsername(username);
    // Same work either way: an unknown or disabled account still pays for one bcrypt compare.
    const matches = await bcrypt.compare(
      password,
      user?.active ? user.password_hash : await this.dummyHash,
    );
    if (!user || !user.active || !matches) {
      this.guard.fail(username);
      throw INVALID();
    }
    this.guard.succeed(username);
    return this.issue(user, now);
  }

  issue(user: UserDoc, now = new Date()): TokenOut {
    const exp = Math.floor(now.getTime() / 1000) + this.ttlMinutes * 60;
    const token = jwt.sign(
      { sub: user._id, role: user.role, jti: randomBytes(12).toString("hex"), exp },
      this.secret,
      { algorithm: "HS256", noTimestamp: true },
    );
    return {
      access_token: token,
      token_type: "bearer",
      expires_at: new Date(exp * 1000).toISOString(),
      user: toUserOut(user),
    };
  }

  /** The signed-in official for a bearer token: valid signature, not expired, not signed out,
   *  account still active. Anything else is 401 "Sign in to continue." */
  async authenticate(header: string | undefined): Promise<AuthenticatedUser> {
    const match = /^Bearer ([A-Za-z0-9._-]+)$/.exec(header ?? "");
    if (!match) throw SIGN_IN();
    let claims: Claims;
    try {
      claims = jwt.verify(match[1]!, this.secret, { algorithms: ["HS256"] }) as Claims;
    } catch {
      throw SIGN_IN();
    }
    if (!claims.sub || !claims.jti || (await this.users.isRevoked(claims.jti))) throw SIGN_IN();
    const user = await this.users.byId(claims.sub);
    if (!user?.active) throw SIGN_IN();
    return { ...toUserOut(user), jti: claims.jti, expiresAt: new Date(claims.exp * 1000) };
  }

  async logout(user: AuthenticatedUser): Promise<void> {
    await this.users.revoke(user.jti, user.expiresAt);
  }
}
