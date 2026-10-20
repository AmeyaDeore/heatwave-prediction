/**
 * Heatwave analysis for our selected Maharashtra places (Part 14 R2; the teacher's M3).
 *
 * Data, all real, nothing synthesised:
 *  - observed history: IMD gridded Tmax 2000–2024 with NASA POWER context, labelled in Python by
 *    IMD-HW-DAILY-v1 (`heatwave-prepare observed`), imported by `npm run import-history`;
 *  - stored predictions (MongoDB `predictions`) for the predicted side;
 *  - the deployed model's held-out metrics (`model_metadata`).
 * Observed and predicted figures are kept apart. Places with identical observed series share
 * an IMD 1° cell: the response says so, so they are not read as independent evidence.
 */
import type { mongo } from "mongoose";
import type { Catalog } from "../catalog.js";
import type { Store } from "../db/store.js";
import { ApiError } from "../http/envelope.js";

interface ObservedDoc {
  region_id: string;
  date: string;
  year: number;
  month: number;
  tmax_c: number;
  normal_tmax_c: number | null;
  temp_deviation_c: number | null;
  risk_class: "NORMAL" | "HEATWAVE" | "SEVERE_HEATWAVE";
}

const HOT = ["HEATWAVE", "SEVERE_HEATWAVE"];
const MIN_YEARS_FOR_TREND = 10;
const round = (v: number, d = 2) => Math.round(v * 10 ** d) / 10 ** d;

/** Ordinary least-squares slope of y on x. */
function slope(points: { x: number; y: number }[]): number {
  const n = points.length;
  const mx = points.reduce((s, p) => s + p.x, 0) / n;
  const my = points.reduce((s, p) => s + p.y, 0) / n;
  const num = points.reduce((s, p) => s + (p.x - mx) * (p.y - my), 0);
  const den = points.reduce((s, p) => s + (p.x - mx) ** 2, 0);
  return den === 0 ? 0 : num / den;
}

/** Longest run of consecutive calendar days in a sorted list of YYYY-MM-DD dates. */
export function longestSpell(dates: string[]): {
  days: number;
  start: string | null;
  end: string | null;
} {
  let best = { days: 0, start: null as string | null, end: null as string | null };
  let runStart = 0;
  for (let i = 0; i < dates.length; i++) {
    const consecutive = i > 0 && Date.parse(dates[i]!) - Date.parse(dates[i - 1]!) === 86_400_000;
    if (!consecutive) runStart = i;
    const days = i - runStart + 1;
    if (days > best.days) best = { days, start: dates[runStart]!, end: dates[i]! };
  }
  return best;
}

export class AnalyticsService {
  constructor(
    private readonly db: () => Promise<mongo.Db>,
    private readonly catalog: Catalog,
    private readonly store: Store,
  ) {}

  private async observed() {
    return (await this.db()).collection<ObservedDoc>("observed_history");
  }

  /** Groups of places whose observed series are identical (they share an IMD cell). */
  private async sharedSeries(): Promise<Map<string, string[]>> {
    const rows = await (
      await this.observed()
    )
      .aggregate<{ _id: string; sum: number; n: number }>([
        { $group: { _id: "$region_id", sum: { $sum: "$tmax_c" }, n: { $sum: 1 } } },
      ])
      .toArray();
    const byKey = new Map<string, string[]>();
    for (const r of rows) {
      const key = `${r.n}:${round(r.sum, 1)}`;
      byKey.set(key, [...(byKey.get(key) ?? []), r._id]);
    }
    const shared = new Map<string, string[]>();
    for (const group of byKey.values()) {
      if (group.length > 1)
        group.forEach((id) =>
          shared.set(
            id,
            group.filter((g) => g !== id),
          ),
        );
    }
    return shared;
  }

  /** History, pattern, records and predictions for one place. */
  async place(regionId: string) {
    if (!this.catalog.has(regionId))
      throw new ApiError(404, "UNKNOWN_REGION", `Unknown region '${regionId}'.`);
    const observed = await this.observed();
    const days = await observed
      .find({ region_id: regionId }, { projection: { _id: 0 }, sort: { date: 1 } })
      .toArray();
    if (days.length === 0) {
      throw new ApiError(
        404,
        "NOT_FOUND",
        `No observed history for '${regionId}' yet. Run npm run import-history.`,
      );
    }

    const years = new Map<number, { days: number; heatwave: number; severe: number }>();
    const months = new Map<
      number,
      { days: number; hot: number; tmax: number; normal: number; normals: number }
    >();
    for (const d of days) {
      const y = years.get(d.year) ?? { days: 0, heatwave: 0, severe: 0 };
      y.days += 1;
      if (d.risk_class === "HEATWAVE") y.heatwave += 1;
      if (d.risk_class === "SEVERE_HEATWAVE") y.severe += 1;
      years.set(d.year, y);
      const m = months.get(d.month) ?? { days: 0, hot: 0, tmax: 0, normal: 0, normals: 0 };
      m.days += 1;
      m.tmax += d.tmax_c;
      if (HOT.includes(d.risk_class)) m.hot += 1;
      if (d.normal_tmax_c != null) {
        m.normal += d.normal_tmax_c;
        m.normals += 1;
      }
      months.set(d.month, m);
    }
    const perYear = [...years.entries()]
      .sort(([a], [b]) => a - b)
      .map(([year, y]) => ({
        year,
        days: y.days,
        heatwave_days: y.heatwave,
        severe_days: y.severe,
      }));
    const trend =
      perYear.length >= MIN_YEARS_FOR_TREND
        ? round(
            slope(perYear.map((y) => ({ x: y.year, y: y.heatwave_days + y.severe_days }))) * 10,
            2,
          )
        : null;
    const hottest = days.reduce((a, b) => (b.tmax_c > a.tmax_c ? b : a));
    const departure = days.reduce((a, b) =>
      (b.temp_deviation_c ?? -99) > (a.temp_deviation_c ?? -99) ? b : a,
    );
    const hotDates = days.filter((d) => HOT.includes(d.risk_class)).map((d) => d.date);

    // Predicted side: stored predictions for this place, per lead (kept apart from observed).
    const predictions = await (
      await this.db()
    )
      .collection("predictions")
      .aggregate<{ _id: { lead: number; risk: string }; n: number }>([
        { $match: { region_id: regionId } },
        { $group: { _id: { lead: "$lead_days", risk: "$risk_class" }, n: { $sum: 1 } } },
      ])
      .toArray();
    const shared = (await this.sharedSeries()).get(regionId) ?? [];

    return {
      region_id: regionId,
      observed: {
        source: "IMD gridded Tmax (1°), labelled by IMD-HW-DAILY-v1",
        from: days[0]!.date,
        to: days.at(-1)!.date,
        days: days.length,
        shares_series_with: shared,
        per_year: perYear,
        heatwave_days_per_decade_trend: trend,
        per_month: [...months.entries()]
          .sort(([a], [b]) => a - b)
          .map(([month, m]) => ({
            month,
            hot_day_share: round(m.hot / m.days, 4),
            hot_days: m.hot,
            mean_tmax_c: round(m.tmax / m.days, 1),
            mean_normal_tmax_c: m.normals ? round(m.normal / m.normals, 1) : null,
          })),
        records: {
          hottest_day: { date: hottest.date, tmax_c: hottest.tmax_c },
          largest_departure: { date: departure.date, temp_deviation_c: departure.temp_deviation_c },
          longest_spell: longestSpell(hotDates),
          heatwave_days: hotDates.length,
        },
      },
      predicted: {
        source: "stored model predictions",
        by_lead: [0, 1, 2, 3].map((lead) => {
          const rows = predictions.filter((p) => p._id.lead === lead);
          return {
            lead_days: lead,
            total: rows.reduce((s, r) => s + r.n, 0),
            NORMAL: rows.find((r) => r._id.risk === "NORMAL")?.n ?? 0,
            HEATWAVE: rows.find((r) => r._id.risk === "HEATWAVE")?.n ?? 0,
            SEVERE_HEATWAVE: rows.find((r) => r._id.risk === "SEVERE_HEATWAVE")?.n ?? 0,
          };
        }),
      },
    };
  }

  /** One row per place: how exposed it has been (observed), and its latest predicted risk. */
  async places(division?: string) {
    const places = this.catalog.inDivision(division);
    const rows = await (
      await this.observed()
    )
      .aggregate<{
        _id: string;
        days: number;
        hot: number;
        severe: number;
        max_tmax: number;
        years: number[];
      }>([
        { $match: { region_id: { $in: places.map((p) => p.id) } } },
        {
          $group: {
            _id: "$region_id",
            days: { $sum: 1 },
            hot: { $sum: { $cond: [{ $in: ["$risk_class", HOT] }, 1, 0] } },
            severe: { $sum: { $cond: [{ $eq: ["$risk_class", "SEVERE_HEATWAVE"] }, 1, 0] } },
            max_tmax: { $max: "$tmax_c" },
            years: { $addToSet: "$year" },
          },
        },
      ])
      .toArray();
    const byId = new Map(rows.map((r) => [r._id, r]));
    const latest = await this.store.latestByRegion(
      0,
      places.map((p) => p.id),
    );
    const shared = await this.sharedSeries();
    return {
      source:
        "IMD gridded Tmax (1°) 2000–2024, labelled by IMD-HW-DAILY-v1; latest stored prediction",
      places: places.map((p) => {
        const r = byId.get(p.id);
        return {
          region_id: p.id,
          name: p.name,
          division: p.division,
          zone: p.zone,
          observed_years: r?.years.length ?? 0,
          heatwave_days: r?.hot ?? 0,
          severe_days: r?.severe ?? 0,
          heatwave_days_per_year: r && r.years.length ? round(r.hot / r.years.length, 2) : null,
          max_tmax_c: r?.max_tmax ?? null,
          shares_series_with: shared.get(p.id) ?? [],
          latest_predicted_risk: latest.get(p.id)?.risk_class ?? null,
        };
      }),
    };
  }

  async model() {
    const model = await this.store.activeModel();
    if (!model)
      throw new ApiError(
        404,
        "NOT_FOUND",
        "No model recorded yet (the ML service has not been reached).",
      );
    return model;
  }
}
