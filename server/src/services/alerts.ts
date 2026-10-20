/**
 * Heatwave alerts on Node.js + MongoDB (Part 09 R2 / Part 13; the teacher's M5).
 *
 * Same contract as the FastAPI service (docs/api/README.md, AlertOut), so the frontend's alert
 * hooks are unchanged. Scope (frozen 2026-10-20): create, list, view, edit a draft, issue.
 * Issuing saves every channel as PENDING in one atomic write, then delivers in the background.
 * **Delivery is mock:** each channel is recorded as NOTIFIED with "mock delivery, nothing sent".
 * No SMS or e-mail provider is called (the Python Part 09 service remains the reference for
 * real SendGrid/Twilio delivery, not ported).
 */
import { readFileSync } from "node:fs";
import { load } from "js-yaml";
import type { mongo } from "mongoose";
import type { Catalog } from "../catalog.js";
import { ApiError } from "../http/envelope.js";
import type { Logger } from "../logger.js";

export type AlertStatus = "DRAFT" | "READY" | "ISSUED";
export type Severity = "HEATWAVE" | "SEVERE_HEATWAVE";

export interface Channel {
  id: string;
  label: string;
  mechanism: "sms" | "email" | "in_app";
}

export interface ChannelDelivery {
  channel: string;
  label: string;
  status: "READY" | "PENDING" | "NOTIFIED" | "FAILED";
  detail: string | null;
  updated_at: string;
}

interface AlertDoc {
  _id: string;
  region_id: string;
  severity: Severity;
  status: AlertStatus;
  message: string;
  channels: ChannelDelivery[];
  prediction_id: string | null;
  created_by: string;
  client_request_id: string;
  created_at: Date;
  issued_at: Date | null;
  updated_at: Date;
}

export function loadChannels(path: string): Channel[] {
  const doc = load(readFileSync(path, "utf8")) as { channels?: Channel[] } | null;
  const channels = doc?.channels ?? [];
  for (const c of channels) {
    if (!["sms", "email", "in_app"].includes(c.mechanism)) {
      throw new Error(`alert_channels.yaml: channel '${c.id}' has an unknown mechanism`);
    }
  }
  return channels;
}

export interface AlertCreate {
  client_request_id: string;
  region_id: string;
  severity: Severity;
  message: string;
  channels: string[];
  status?: AlertStatus;
  prediction_id?: string | null;
}

export interface AlertUpdate {
  severity?: Severity;
  message?: string;
  channels?: string[];
  status?: AlertStatus;
}

const ALLOWED: Record<AlertStatus, AlertStatus[]> = {
  DRAFT: ["DRAFT", "READY", "ISSUED"],
  READY: ["READY", "DRAFT", "ISSUED"],
  ISSUED: [],
};

export class AlertService {
  private readonly channels: Map<string, Channel>;

  constructor(
    private readonly db: () => Promise<mongo.Db>,
    private readonly catalog: Catalog,
    channels: Channel[],
    private readonly logger: Logger,
    /** Background delivery delay per channel (ms); 0 in tests that want it immediate. */
    private readonly deliveryDelayMs = 400,
  ) {
    this.channels = new Map(channels.map((c) => [c.id, c]));
  }

  listChannels(): Channel[] {
    return [...this.channels.values()];
  }

  private async alerts() {
    return (await this.db()).collection<AlertDoc>("alerts");
  }

  private out(doc: AlertDoc) {
    const place = this.catalog.byId.get(doc.region_id);
    const summary = {
      total: doc.channels.length,
      notified: doc.channels.filter((c) => c.status === "NOTIFIED").length,
      failed: doc.channels.filter((c) => c.status === "FAILED").length,
      pending: doc.channels.filter((c) => c.status === "PENDING").length,
    };
    return {
      alert_id: doc._id,
      status: doc.status,
      severity: doc.severity,
      region: place ?? { id: doc.region_id },
      message: doc.message,
      prediction_id: doc.prediction_id,
      channels: doc.channels,
      delivery_summary: {
        ...summary,
        all_delivered: summary.total > 0 && summary.notified === summary.total,
      },
      created_at: doc.created_at.toISOString(),
      created_by: doc.created_by,
      issued_at: doc.issued_at ? doc.issued_at.toISOString() : null,
      updated_at: doc.updated_at.toISOString(),
    };
  }

  private validate(body: { region_id?: string; channels?: string[] }) {
    if (body.region_id !== undefined && !this.catalog.has(body.region_id)) {
      throw new ApiError(404, "UNKNOWN_REGION", `Unknown region '${body.region_id}'.`);
    }
    const unknown = (body.channels ?? []).filter((c) => !this.channels.has(c));
    if (unknown.length) {
      throw new ApiError(
        400,
        "BAD_REQUEST",
        `Unknown channel(s): ${unknown.join(", ")}.`,
        "client",
        {
          valid: [...this.channels.keys()],
        },
      );
    }
  }

  private deliveries(ids: string[], status: "READY" | "PENDING", now: Date): ChannelDelivery[] {
    return [...new Set(ids)].map((id) => ({
      channel: id,
      label: this.channels.get(id)!.label,
      status,
      detail: null,
      updated_at: now.toISOString(),
    }));
  }

  private async nextId(year: number): Promise<string> {
    const counters = (await this.db()).collection<{ _id: string; seq: number }>("counters");
    const row = await counters.findOneAndUpdate(
      { _id: `alert-${year}` },
      { $inc: { seq: 1 } },
      { upsert: true, returnDocument: "after" },
    );
    return `HW-${year}-${String(row!.seq).padStart(4, "0")}`;
  }

  async list(filters: { status?: AlertStatus; region_id?: string; limit: number; offset: number }) {
    const alerts = await this.alerts();
    const query: Record<string, unknown> = {};
    if (filters.status) query.status = filters.status;
    if (filters.region_id) query.region_id = filters.region_id;
    const [docs, total] = await Promise.all([
      alerts
        .find(query)
        .sort({ created_at: -1 })
        .skip(filters.offset)
        .limit(filters.limit)
        .toArray(),
      alerts.countDocuments(query),
    ]);
    return {
      alerts: docs.map((d) => this.out(d)),
      total,
      limit: filters.limit,
      offset: filters.offset,
    };
  }

  async get(id: string) {
    const doc = await (await this.alerts()).findOne({ _id: id });
    if (!doc) throw new ApiError(404, "NOT_FOUND", `Alert '${id}' does not exist.`);
    return this.out(doc);
  }

  async create(body: AlertCreate, userId: string) {
    this.validate(body);
    const alerts = await this.alerts();
    // Idempotent: the same form submitted twice returns the first alert, notifies nobody again.
    const replay = await alerts.findOne({
      created_by: userId,
      client_request_id: body.client_request_id,
    });
    if (replay) {
      const same =
        replay.region_id === body.region_id &&
        replay.severity === body.severity &&
        replay.message === body.message;
      if (!same)
        throw new ApiError(
          409,
          "CONFLICT",
          "This request id was already used for a different alert.",
        );
      return { alert: { ...this.out(replay), idempotent_replay: true }, created: false };
    }
    const now = new Date();
    const status = body.status ?? "DRAFT";
    const doc: AlertDoc = {
      _id: await this.nextId(now.getUTCFullYear()),
      region_id: body.region_id,
      severity: body.severity,
      status,
      message: body.message,
      channels: this.deliveries(body.channels, status === "ISSUED" ? "PENDING" : "READY", now),
      prediction_id: body.prediction_id ?? null,
      created_by: userId,
      client_request_id: body.client_request_id,
      created_at: now,
      issued_at: status === "ISSUED" ? now : null,
      updated_at: now,
    };
    await alerts.insertOne(doc);
    if (status === "ISSUED") this.deliverLater(doc._id);
    return { alert: this.out(doc), created: true };
  }

  async update(id: string, changes: AlertUpdate) {
    this.validate(changes);
    const alerts = await this.alerts();
    const doc = await alerts.findOne({ _id: id });
    if (!doc) throw new ApiError(404, "NOT_FOUND", `Alert '${id}' does not exist.`);
    if (doc.status === "ISSUED") {
      throw new ApiError(
        409,
        "CONFLICT",
        "This alert was issued and cannot be changed. Create a new alert instead.",
      );
    }
    const next = changes.status ?? doc.status;
    if (!ALLOWED[doc.status].includes(next)) {
      throw new ApiError(409, "CONFLICT", `An alert cannot move from ${doc.status} to ${next}.`);
    }
    const now = new Date();
    const channelIds = changes.channels ?? doc.channels.map((c) => c.channel);
    const set: Partial<AlertDoc> = {
      severity: changes.severity ?? doc.severity,
      message: changes.message ?? doc.message,
      status: next,
      channels: this.deliveries(channelIds, next === "ISSUED" ? "PENDING" : "READY", now),
      updated_at: now,
      ...(next === "ISSUED" ? { issued_at: now } : {}),
    };
    // Conditional on "not issued": two officials cannot issue or edit the same alert twice.
    const result = await alerts.findOneAndUpdate(
      { _id: id, status: { $ne: "ISSUED" } },
      { $set: set },
      { returnDocument: "after" },
    );
    if (!result) throw new ApiError(409, "CONFLICT", "This alert was issued meanwhile.");
    if (next === "ISSUED") this.deliverLater(id);
    return this.out(result);
  }

  /** Mock delivery in the background: each PENDING channel becomes NOTIFIED, one by one. */
  private deliverLater(id: string) {
    void (async () => {
      try {
        const alerts = await this.alerts();
        const doc = await alerts.findOne({ _id: id });
        for (const delivery of doc?.channels ?? []) {
          if (delivery.status !== "PENDING") continue;
          if (this.deliveryDelayMs) await new Promise((r) => setTimeout(r, this.deliveryDelayMs));
          const mechanism = this.channels.get(delivery.channel)?.mechanism ?? "unknown";
          await alerts.updateOne(
            { _id: id, "channels.channel": delivery.channel },
            {
              $set: {
                "channels.$.status": "NOTIFIED",
                "channels.$.detail": `Mock delivery (${mechanism}): recorded, no real message sent`,
                "channels.$.updated_at": new Date().toISOString(),
                updated_at: new Date(),
              },
            },
          );
        }
        this.logger.info("alert delivered (mock)", { alert_id: id });
      } catch (error) {
        this.logger.warning("alert delivery interrupted; it resumes at the next start", {
          alert_id: id,
          error: error instanceof Error ? error.message : String(error),
        });
      }
    })();
  }

  /** At startup: finish deliveries a stop interrupted (at-least-once, as in Part 09). */
  async resumePending(): Promise<number> {
    const stranded = await (
      await this.alerts()
    )
      .find({ status: "ISSUED", "channels.status": "PENDING" }, { projection: { _id: 1 } })
      .toArray();
    stranded.forEach((d) => this.deliverLater(d._id));
    return stranded.length;
  }
}
