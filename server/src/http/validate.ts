/**
 * Request validation with zod, the FastAPI way: bodies are strict (an unknown field is a 422,
 * never ignored), and a 422 lists only where and why, never the submitted value.
 */
import type { Request } from "express";
import { z } from "zod";
import { ApiError } from "./envelope.js";

export const RegionId = z.string().regex(/^[a-z][a-z0-9_]{1,40}$/, "must be a region id");
export const LeadDays = z.coerce.number().int().min(0).max(3);

function invalid(error: z.ZodError, where: "body" | "query"): ApiError {
  const details = error.issues.map((issue) => ({
    field: issue.path.length ? issue.path.join(".") : where,
    message: issue.message,
  }));
  return new ApiError(422, "VALIDATION_ERROR", "The request is not valid.", "client", details);
}

export function parseBody<T extends z.ZodType>(schema: T, req: Request): z.output<T> {
  const parsed = schema.safeParse(req.body ?? {});
  if (!parsed.success) throw invalid(parsed.error, "body");
  return parsed.data;
}

export function parseQuery<T extends z.ZodType>(schema: T, req: Request): z.output<T> {
  const parsed = schema.safeParse(req.query);
  if (!parsed.success) throw invalid(parsed.error, "query");
  return parsed.data;
}
