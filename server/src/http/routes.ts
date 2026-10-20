/**
 * /api/v1 routes served by the Node.js API (Part 07 §B). Shapes, codes and strictness match
 * docs/api/README.md, so the Part 10 frontend can switch to this API unchanged (step 5).
 *
 * Revision 2 step 4: places, weather, predictions (single, batch, latest, latest-by-region,
 * by id). Login, alerts and analytics arrive in steps 5, 8 and 9. Until step 5 adds login,
 * these routes are open, as the FastAPI reads are today.
 */
import { Router } from "express";
import { z } from "zod";
import type { Catalog } from "../catalog.js";
import type { AlertService } from "../services/alerts.js";
import type { AnalyticsService } from "../services/analytics.js";
import type { PredictionService } from "../services/predictions.js";
import { sendOk } from "./envelope.js";
import type { RateLimiter } from "./ratelimit.js";
import { LeadDays, parseBody, parseQuery, RegionId } from "./validate.js";

export interface ApiDependencies {
  catalog: Catalog;
  predictions: PredictionService;
  limiter: RateLimiter;
  /** Step 8 (M5): alerts on MongoDB. */
  alerts?: AlertService;
  /** Step 9 (M3): analysis of the selected Maharashtra places. */
  analytics?: AnalyticsService;
}

const Severity = z.enum(["HEATWAVE", "SEVERE_HEATWAVE"]);
const AlertStatus = z.enum(["DRAFT", "READY", "ISSUED"]);
const ChannelIds = z.array(z.string().min(1).max(60)).min(1).max(20);
const AlertCreateBody = z.strictObject({
  client_request_id: z.uuid(),
  region_id: RegionId,
  severity: Severity,
  message: z.string().trim().min(10).max(1000),
  channels: ChannelIds,
  status: AlertStatus.default("DRAFT"),
  prediction_id: z.string().max(40).nullable().optional(),
});
const AlertUpdateBody = z.strictObject({
  severity: Severity.optional(),
  message: z.string().trim().min(10).max(1000).optional(),
  channels: ChannelIds.optional(),
  status: AlertStatus.optional(),
});
const AlertListQuery = z.object({
  status: AlertStatus.optional(),
  region_id: RegionId.optional(),
  limit: z.coerce.number().int().min(1).max(100).default(25),
  offset: z.coerce.number().int().min(0).default(0),
});

const PredictBody = z.strictObject({ region_id: RegionId, lead_days: LeadDays.default(0) });

const BatchBody = z.strictObject({
  region_ids: z.array(RegionId).min(1).max(100).optional(),
  lead_days: z.array(z.number().int().min(0).max(3)).min(1).max(4).optional(),
  only_missing: z.boolean().default(false),
});

const LeadQuery = z.object({ lead_days: LeadDays.default(0) });

export function apiRouter({
  catalog,
  predictions,
  limiter,
  alerts,
  analytics,
}: ApiDependencies): Router {
  const router = Router();

  // -- reference --------------------------------------------------------------------
  router.get("/regions", (_req, res) => {
    sendOk(res, catalog.places);
  });

  // -- weather ------------------------------------------------------------------------
  router.get("/weather", async (req, res) => {
    const q = parseQuery(LeadQuery.extend({ region_id: RegionId.optional() }), req);
    sendOk(res, await predictions.weather(q.region_id, q.lead_days));
  });

  // -- predictions --------------------------------------------------------------------
  router.post("/predict", limiter.middleware("predict"), async (req, res) => {
    const body = parseBody(PredictBody, req);
    const prediction = await predictions.predict(body.region_id, body.lead_days);
    res.locals.logFields = {
      risk_class: prediction.risk_class,
      region_id: body.region_id,
      lead_days: body.lead_days,
    };
    sendOk(res, prediction);
  });

  router.post("/predictions/batch", limiter.middleware("predict"), async (req, res) => {
    const body = parseBody(BatchBody, req);
    const result = await predictions.scoreBatch(body);
    res.locals.logFields = { scored: result.scored, skipped: result.skipped };
    sendOk(res, result);
  });

  router.get("/predictions/latest", async (req, res) => {
    const q = parseQuery(LeadQuery.extend({ region_id: RegionId }), req);
    sendOk(res, await predictions.latest(q.region_id, q.lead_days));
  });

  // Registered before /predictions/:id, which would otherwise capture it.
  router.get("/predictions/latest-by-region", async (req, res) => {
    const q = parseQuery(LeadQuery.extend({ division: z.string().min(1).max(60).optional() }), req);
    sendOk(res, await predictions.latestByRegion(q.lead_days, q.division));
  });

  router.get("/predictions/:predictionId", async (req, res) => {
    sendOk(res, await predictions.byId(req.params.predictionId));
  });

  // -- alerts (step 8, M5) ----------------------------------------------------------
  if (alerts) {
    router.get("/alert-channels", (_req, res) => {
      sendOk(res, alerts.listChannels());
    });
    router.get("/alerts", async (req, res) => {
      sendOk(res, await alerts.list(parseQuery(AlertListQuery, req)));
    });
    router.get("/alerts/:alertId", async (req, res) => {
      sendOk(res, await alerts.get(String(req.params.alertId)));
    });
    router.post("/alerts", limiter.middleware("alerts"), async (req, res) => {
      const body = parseBody(AlertCreateBody, req);
      const { alert, created } = await alerts.create(body, String(res.locals.userId));
      res.locals.logFields = { alert_id: alert.alert_id, alert_status: alert.status };
      sendOk(res, alert, created ? 201 : 200);
    });
    router.patch("/alerts/:alertId", limiter.middleware("alerts"), async (req, res) => {
      const alert = await alerts.update(
        String(req.params.alertId),
        parseBody(AlertUpdateBody, req),
      );
      res.locals.logFields = { alert_id: alert.alert_id, alert_status: alert.status };
      sendOk(res, alert);
    });
  }

  // -- analytics (step 9, M3) -------------------------------------------------------
  if (analytics) {
    router.get("/analytics/places", async (req, res) => {
      const q = parseQuery(z.object({ division: z.string().min(1).max(60).optional() }), req);
      sendOk(res, await analytics.places(q.division));
    });
    router.get("/analytics/place", async (req, res) => {
      sendOk(
        res,
        await analytics.place(parseQuery(z.object({ region_id: RegionId }), req).region_id),
      );
    });
    router.get("/analytics/model", async (_req, res) => {
      sendOk(res, await analytics.model());
    });
  }

  return router;
}
