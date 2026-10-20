/**
 * Analytics: heatwave analysis for our selected Maharashtra places (Part 14 + R2; the
 * teacher's M3). Real data only:
 *  - Observed: IMD gridded daily Tmax 2000–2024 (1° grid), labelled in Python by the
 *    IMD-HW-DAILY-v1 rule; places sharing a grid cell are disclosed.
 *  - Predicted: the model predictions stored so far (kept separate from observed).
 *  - Model: the deployed model's held-out metrics.
 * Place = the global selection; `?compare=a,b` (from the dashboard) narrows the comparison.
 */
import { CalendarRange, Flame, MapPinned, Thermometer, Timer } from "lucide-react";
import { useSearchParams } from "react-router";
import { DataSourceTag } from "@/components/shared/data-source-tag";
import { MetricCard } from "@/components/shared/metric-card";
import { PageHeader, Panel } from "@/components/shared/panel";
import { RiskBadge } from "@/components/shared/risk-badge";
import { EmptyState, LoadingState, QueryState } from "@/components/shared/states";
import { Button } from "@/components/ui/button";
import { formatFeatureValue, formatProbability, riskLabel, RISK_CLASSES } from "@/design/labels";
import { layout, typography } from "@/design/tokens";
import type { PlaceAnalyticsOut } from "@/lib/api/types";
import { env } from "@/lib/env";
import { forecastLabel, formatHistoricDate } from "@/lib/format";
import { useModelMetadata, usePlaceAnalytics, usePlacesAnalytics } from "@/lib/query/hooks";
import { cn } from "@/lib/utils";
import { regionDisplayName, useRegion } from "@/state/region-context";

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** Stacked bars (heatwave + severe days) per year, plain SVG in the risk tokens. */
function YearBars({ perYear }: { perYear: PlaceAnalyticsOut["observed"]["per_year"] }) {
  const max = Math.max(1, ...perYear.map((y) => y.heatwave_days + y.severe_days));
  const w = 640;
  const h = 160;
  const bw = w / perYear.length;
  return (
    <figure className="flex flex-col gap-2">
      <svg
        viewBox={`0 0 ${w} ${h + 18}`}
        className="h-auto w-full"
        role="img"
        aria-label="Heatwave days per year"
      >
        <line x1={0} x2={w} y1={h} y2={h} stroke="var(--border)" />
        {perYear.map((y, i) => {
          const hw = (y.heatwave_days / max) * (h - 8);
          const sv = (y.severe_days / max) * (h - 8);
          return (
            <g key={y.year}>
              <title>{`${y.year}: ${y.heatwave_days} heatwave, ${y.severe_days} severe days`}</title>
              <rect
                x={i * bw + 2}
                y={h - hw}
                width={bw - 4}
                height={hw}
                fill="var(--risk-heatwave)"
              />
              <rect
                x={i * bw + 2}
                y={h - hw - sv}
                width={bw - 4}
                height={sv}
                fill="var(--risk-severe)"
              />
              {(i % 4 === 0 || i === perYear.length - 1) && (
                <text
                  x={i * bw + bw / 2}
                  y={h + 14}
                  textAnchor="middle"
                  className="fill-muted-foreground text-[10px]"
                >
                  {y.year}
                </text>
              )}
            </g>
          );
        })}
      </svg>
      <figcaption className="flex gap-4 text-xs text-muted-foreground">
        <span className="inline-flex items-center gap-1.5">
          <span aria-hidden="true" className="size-2.5 rounded-sm bg-risk-heatwave" />{" "}
          {riskLabel("HEATWAVE")} days
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span aria-hidden="true" className="size-2.5 rounded-sm bg-risk-severe" />{" "}
          {riskLabel("SEVERE_HEATWAVE")} days
        </span>
        <span>Tallest bar: {max} days</span>
      </figcaption>
    </figure>
  );
}

/** Month-by-month: mean max temperature against the seasonal normal, and heatwave days. */
function MonthTable({ perMonth }: { perMonth: PlaceAnalyticsOut["observed"]["per_month"] }) {
  const hottest = Math.max(...perMonth.map((m) => m.mean_tmax_c));
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[34rem] text-sm">
        <caption className="sr-only">Seasonal pattern</caption>
        <thead className="text-left text-xs text-muted-foreground">
          <tr className="border-b">
            <th className="py-1.5 font-medium">Month</th>
            <th className="py-1.5 pl-3 text-right font-medium">Mean max</th>
            <th className="py-1.5 pl-3 text-right font-medium">Normal</th>
            <th className="py-1.5 pl-3 font-medium">Heatwave days (all years)</th>
          </tr>
        </thead>
        <tbody>
          {perMonth.map((m) => (
            <tr
              key={m.month}
              className={cn("border-b last:border-0", m.mean_tmax_c === hottest && "bg-muted")}
            >
              <td className="py-1.5">{MONTHS[m.month - 1]}</td>
              <td className="tabular py-1.5 pl-3 text-right">
                {formatFeatureValue("tmax_c", m.mean_tmax_c)}
              </td>
              <td className="tabular py-1.5 pl-3 text-right">
                {m.mean_normal_tmax_c == null
                  ? "—"
                  : formatFeatureValue("normal_tmax_c", m.mean_normal_tmax_c)}
              </td>
              <td className="py-1.5 pl-3">
                <span className="inline-flex items-center gap-2">
                  <span
                    className="inline-block h-2 rounded-full bg-risk-heatwave"
                    style={{ width: `${Math.min(100, m.hot_days * 4)}px` }}
                    aria-hidden="true"
                  />
                  <span className="tabular">{m.hot_days}</span>
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function AnalyticsPage() {
  const { regionId, region, regions, setRegionId } = useRegion();
  const [params, setParams] = useSearchParams();
  const compare = (params.get("compare") ?? "").split(",").filter(Boolean);
  const place = usePlaceAnalytics(regionId);
  const places = usePlacesAnalytics();
  const model = useModelMetadata();
  const nameOf = (id: string) => regions.find((r) => r.id === id)?.name ?? id;

  return (
    <div className={cn(layout.page, layout.pageStack)}>
      <PageHeader
        title="Analytics"
        subtitle="Historical heatwave patterns and model performance for our selected Maharashtra places"
        context={
          <span className="inline-flex items-center gap-1 text-sm font-medium">
            <MapPinned aria-hidden="true" className="size-4 text-muted-foreground" />
            {regionDisplayName(region, regionId)}
          </span>
        }
      />

      <QueryState
        query={place}
        notFoundAsEmpty
        loading={<LoadingState shape="chart" />}
        empty={
          <EmptyState
            title="No observed history for this place yet"
            description="Import it with npm run import-history (server/)."
          />
        }
      >
        {(a) => {
          const o = a.observed;
          return (
            <div className="flex flex-col gap-6">
              {o.shares_series_with.length > 0 && (
                <p
                  role="note"
                  className="rounded-lg border border-tone-warning-border bg-tone-warning-subtle px-4 py-2 text-sm text-tone-warning-subtle-fg"
                >
                  {region?.name ?? regionId} shares its observed IMD grid cell (1°, about 110 km)
                  with {o.shares_series_with.map(nameOf).join(", ")}: their observed history is the
                  same series, not independent evidence.
                </p>
              )}
              <div className={cn(layout.grid, "sm:grid-cols-2 xl:grid-cols-4")}>
                <MetricCard
                  label="Heatwave days observed"
                  icon={Flame}
                  value={String(o.records.heatwave_days)}
                  subLabel={`${formatHistoricDate(o.from)} – ${formatHistoricDate(o.to)}`}
                />
                <MetricCard
                  label="Hottest day"
                  icon={Thermometer}
                  value={formatFeatureValue("tmax_c", o.records.hottest_day.tmax_c)}
                  subLabel={formatHistoricDate(o.records.hottest_day.date)}
                />
                <MetricCard
                  label="Longest heatwave spell"
                  icon={Timer}
                  value={
                    o.records.longest_spell.days ? `${o.records.longest_spell.days} days` : "None"
                  }
                  subLabel={
                    o.records.longest_spell.start
                      ? `${formatHistoricDate(o.records.longest_spell.start)} – ${formatHistoricDate(o.records.longest_spell.end!)}`
                      : "No heatwave day observed"
                  }
                />
                <MetricCard
                  label="Largest departure"
                  icon={CalendarRange}
                  value={
                    o.records.largest_departure.temp_deviation_c == null
                      ? "—"
                      : formatFeatureValue(
                          "temp_deviation_c",
                          o.records.largest_departure.temp_deviation_c,
                        )
                  }
                  subLabel={formatHistoricDate(o.records.largest_departure.date)}
                />
              </div>

              <div className={cn(layout.grid, "lg:grid-cols-2")}>
                <Panel
                  title="Heatwave days per year"
                  description={o.source}
                  tags={
                    <DataSourceTag
                      kind="live"
                      label="Observed"
                      title="Observed history, not model output"
                    />
                  }
                  footer={
                    o.heatwave_days_per_decade_trend === null
                      ? "Too few years for a trend."
                      : `Trend: ${o.heatwave_days_per_decade_trend > 0 ? "+" : ""}${o.heatwave_days_per_decade_trend} heatwave days per decade (least-squares, ${o.per_year.length} years). A small sample: read it as a tendency, not a forecast.`
                  }
                >
                  <YearBars perYear={o.per_year} />
                </Panel>
                <Panel
                  title="Seasonal pattern"
                  description="When in the year this place is at risk (observed)."
                  tags={
                    <DataSourceTag
                      kind="live"
                      label="Observed"
                      title="Observed history, not model output"
                    />
                  }
                >
                  <MonthTable perMonth={o.per_month} />
                </Panel>
              </div>

              <Panel
                title="Predicted risk so far"
                description={`${a.predicted.source}, by forecast day. Model output, kept apart from the observed history above.`}
                tags={<DataSourceTag kind="ai" />}
                footer={
                  region && region.zone !== "coastal" && !env.inlandModelValidated
                    ? "Model not yet validated for inland places: the predicted counts for this place are indicative."
                    : undefined
                }
              >
                <table className="w-full text-sm">
                  <caption className="sr-only">Stored predictions by forecast day</caption>
                  <thead className="text-left text-xs text-muted-foreground">
                    <tr className="border-b">
                      <th className="py-1.5 font-medium">Forecast day</th>
                      <th className="py-1.5 pl-3 text-right font-medium">Predictions</th>
                      {RISK_CLASSES.map((rc) => (
                        <th key={rc} className="py-1.5 pl-3 text-right font-medium">
                          {riskLabel(rc)}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {a.predicted.by_lead.map((row) => (
                      <tr key={row.lead_days} className="border-b last:border-0">
                        <td className="py-1.5">{forecastLabel(row.lead_days)}</td>
                        <td className="tabular py-1.5 pl-3 text-right">{row.total}</td>
                        {RISK_CLASSES.map((rc) => (
                          <td key={rc} className="tabular py-1.5 pl-3 text-right">
                            {row[rc]}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </Panel>
            </div>
          );
        }}
      </QueryState>

      <Panel
        title={compare.length ? "Compare places" : "Place comparison"}
        description="Observed heatwave exposure (IMD 2000–2024) and the latest predicted risk, across our selected places. Select a row to analyse that place."
        action={
          compare.length ? (
            <Button size="sm" variant="ghost" onClick={() => setParams({}, { replace: true })}>
              Show all places
            </Button>
          ) : undefined
        }
      >
        <QueryState query={places} loading={<LoadingState shape="list" rows={6} />}>
          {(data) => {
            const rows = data.places
              .filter((p) => !compare.length || compare.includes(p.region_id))
              .sort((x, y) => (y.heatwave_days_per_year ?? -1) - (x.heatwave_days_per_year ?? -1));
            return (
              <div className="overflow-x-auto">
                <table className="w-full min-w-[40rem] text-sm">
                  <caption className="sr-only">Place comparison</caption>
                  <thead className="text-left text-xs text-muted-foreground">
                    <tr className="border-b">
                      <th className="py-1.5 font-medium">Place</th>
                      <th className="py-1.5 pl-3 font-medium">Division</th>
                      <th className="py-1.5 pl-3 text-right font-medium">Heatwave days / year</th>
                      <th className="py-1.5 pl-3 text-right font-medium">Severe days</th>
                      <th className="py-1.5 pl-3 text-right font-medium">Record max</th>
                      <th className="py-1.5 pl-3 font-medium">Latest predicted (today)</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((p) => (
                      <tr
                        key={p.region_id}
                        aria-selected={p.region_id === regionId}
                        onClick={() => setRegionId(p.region_id)}
                        className={cn(
                          "cursor-pointer border-b last:border-0 hover:bg-muted/60",
                          p.region_id === regionId && "bg-muted",
                        )}
                      >
                        <td className="py-1.5">
                          <button
                            type="button"
                            className="text-left font-medium"
                            onClick={() => setRegionId(p.region_id)}
                          >
                            {p.name}
                          </button>
                          {p.shares_series_with.length > 0 && (
                            <span className="block text-xs text-muted-foreground">
                              same observed series as {p.shares_series_with.map(nameOf).join(", ")}
                            </span>
                          )}
                        </td>
                        <td className="py-1.5 pl-3">{p.division ?? "—"}</td>
                        <td className="tabular py-1.5 pl-3 text-right">
                          {p.heatwave_days_per_year ?? "—"}
                        </td>
                        <td className="tabular py-1.5 pl-3 text-right">{p.severe_days}</td>
                        <td className="tabular py-1.5 pl-3 text-right whitespace-nowrap">
                          {p.max_tmax_c == null ? "—" : formatFeatureValue("tmax_c", p.max_tmax_c)}
                        </td>
                        <td className="py-1.5 pl-3">
                          {p.latest_predicted_risk ? (
                            <RiskBadge riskClass={p.latest_predicted_risk} size="sm" />
                          ) : (
                            <span className="text-xs text-muted-foreground">Not scored</span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            );
          }}
        </QueryState>
      </Panel>

      <Panel
        title="Model performance"
        description="The deployed model's metrics on its held-out test set (not recomputed here)."
        footer={
          !env.inlandModelValidated
            ? "Measured on the coastal Mumbai test set the model was trained for. Not yet validated for inland places (Revision 2 step 10)."
            : undefined
        }
      >
        <QueryState
          query={model}
          notFoundAsEmpty
          empty={<EmptyState title="No model recorded yet" />}
        >
          {(m) => (
            <div className="flex flex-col gap-3">
              <div className={cn(layout.grid, "grid-cols-2 sm:grid-cols-4")}>
                {[
                  ["Precision (macro)", m.precision_macro],
                  ["Recall (macro)", m.recall_macro],
                  ["F1 score (macro)", m.f1_macro],
                  ["Mean confidence", m.mean_confidence],
                ].map(([label, value]) => (
                  <MetricCard
                    key={label as string}
                    label={label as string}
                    value={formatProbability(value as number)}
                  />
                ))}
              </div>
              <p className={typography.secondary}>
                Model <span className="font-mono">{m.model_version}</span> · {m.evaluated_on}
              </p>
            </div>
          )}
        </QueryState>
      </Panel>
    </div>
  );
}
