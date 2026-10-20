/**
 * /api/v1/auth (Part 15 R2) and the guard every other data route sits behind.
 *
 * Auth matrix (Part 15 R2.2): open = POST /auth/login, GET /health, GET /health/ready (and the
 * public advisory feed, step 8). Everything else under /api/v1 needs a valid, unrevoked token.
 */
import { Router, type RequestHandler } from "express";
import { z } from "zod";
import type { AuthenticatedUser, AuthService } from "../auth/service.js";
import { sendOk } from "./envelope.js";
import type { RateLimiter } from "./ratelimit.js";
import { parseBody } from "./validate.js";

const LoginBody = z.strictObject({
  username: z.string().min(1).max(64),
  password: z.string().min(1).max(200),
});

/** 401 "Sign in to continue." unless the request carries a valid session. */
export function requireAuth(auth: AuthService): RequestHandler {
  return async (req, res, next) => {
    try {
      const user = await auth.authenticate(req.get("Authorization"));
      res.locals.user = user;
      res.locals.userId = user.id;
      next();
    } catch (error) {
      next(error);
    }
  };
}

export function authRouter(auth: AuthService, limiter: RateLimiter): Router {
  const router = Router();

  router.post("/auth/login", limiter.middleware("login"), async (req, res, next) => {
    try {
      const body = parseBody(LoginBody, req);
      const token = await auth.login(body.username, body.password);
      res.locals.userId = token.user.id;
      sendOk(res, token);
    } catch (error) {
      const retry = (error as { retryAfter?: number }).retryAfter;
      if (retry) res.setHeader("Retry-After", String(retry));
      next(error);
    }
  });

  router.get("/auth/me", requireAuth(auth), (_req, res) => {
    const user = res.locals.user as AuthenticatedUser;
    // The public UserOut only: never the token id or expiry.
    sendOk(res, {
      id: user.id,
      username: user.username,
      display_name: user.display_name,
      role: user.role,
    });
  });

  router.post("/auth/logout", requireAuth(auth), async (_req, res) => {
    await auth.logout(res.locals.user as AuthenticatedUser);
    sendOk(res, { signed_out: true });
  });

  return router;
}
