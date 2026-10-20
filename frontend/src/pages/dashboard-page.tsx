/**
 * Heatwave Command Center (Part 11, with Revision 2: the interactive Maharashtra map, M4).
 *
 * Data: `latest-by-region` (stored predictions for every place at the chosen lead) and
 * all-places `weather` for the same lead feed the map, the table and three metric cards; the
 * Forecast card also reads the other three leads' snapshots (cached, reused when switching).
 * Every number shown is an API field, formatted, never recomputed.
 *
 * Decisions (owner, 2026-10-20): a map marker or table row selects the place and stays here
 * ("Details" opens the Prediction page); places without a prediction are scored only by the
 * explicit "Score places" button (or the score-all CLI), never on page view.
 */
import {
  BarChart3,
  Brain,
  Droplets,
  Gauge,
  ListChecks,
  MapPinned,
  Sparkles,
  Thermometer,
  TriangleAlert,
} from "lucide-react";
import { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router";
import { toast } from "sonner";
import { ActionList } from "@/components/shared/action-list";
import { FactorList } from "@/components/shared/contributing-factor-bar";
import { DataSourceTag } from "@/components/shared/data-source-tag";
import { MaharashtraMap, type MapValue } from "@/components/shared/maharashtra-map";
import { MetricCard } from "@/components/shared/metric-card";
import { PageHeader, Panel } from "@/components/shared/panel";
import { RiskBadge } from "@/components/shared/risk-badge";
import { EmptyState, ErrorState, LoadingState } from "@/components/shared/states";
import { Button } from "@/components/ui/button";
import {
  formatFeatureValue,
  formatProbability,
  RISK_CLASSES,
  riskLabel,
  type RiskClass,
} from "@/design/labels";
import { niceRange, type MapScale } from "@/design/map";
import { layout, typography } from "@/design/tokens";
import { describeError } from "@/lib/api/errors";
import type { PredictionOut, RegionOut, WeatherOut } from "@/lib/api/types";
import { env } from "@/lib/env";
import { formatCalendarDate, formatRelative, forecastLabel } from "@/lib/format";
import { useLatestByRegion, useScoreMissing, useWeather } from "@/lib/query/hooks";
import { cn } from "@/lib/utils";
import { regionDisplayName, useRegion, withRegion } from "@/state/region-context";

type Layer = "risk" | "tmax" | "departure";
const LAYERS: { id: Layer; label: string }[] = [
  { id: "risk", label: "Predicted risk" },
  { id: "tmax", label: "Forecast max temp" },
  { id: "departure", label: "Departure from normal" },
];
const LEADS = [0, 1, 2, 3] as const;
const MAX_COMPARE = 4;
const severity = (rc: RiskClass | undefined) => (rc ? RISK_CLASSES.indexOf(rc) : -1);

function Segmented<T extends string | number>({
  label,
  options,
  value,
  onChange,
}: {
  label: string;
  options: { id: T; label: string }[];
  value: T;
  onChange: (v: T) => void;
}) {
  return (
    <div
      role="group"
      aria-label={label}
      className="inline-flex max-w-full flex-wrap rounded-lg border bg-muted p-0.5"
    >
      {options.map((o) => (
        <button
          key={String(o.id)}
          type="button"
          aria-pressed={o.id === value}
          onClick={() => onChange(o.id)}
          className={cn(
            "h-7 rounded-md px-2.5 text-xs font-medium whitespace-nowrap text-muted-foreground outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50",
            o.id === value && "bg-card text-foreground shadow-xs",
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

function inlandCaveat(place: RegionOut | undefined): boolean {
  return Boolean(place && place.zone !== "coastal" && !env.inlandModelValidated);
}

export function DashboardPage() {
  const navigate = useNavigate();
  const { regionId, region, regions, setRegionId } = useRegion();
  const [lead, setLead] = useState<number>(0);
  const [layer, setLayer] = useState<Layer>("risk");
  const [division, setDivision] = useState<string>("all");
  const [compare, setCompare] = useState<string[]>([]);

  const snapshot = useLatestByRegion(lead);
  const weather = useWeather(null, lead);
  const outlook = [useLatestByRegion(1), useLatestByRegion(2), useLatestByRegion(3)];
  const score = useScoreMissing();

  const byId = useMemo(
    () => new Map((snapshot.data?.items ?? []).map((p) => [p.region.id, p])),
    [snapshot.data],
  );
  const weatherById = useMemo(
    () => new Map((weather.data ?? []).map((w) => [w.region.id, w])),
    [weather.data],
  );
  const divisions = useMemo(
    () => [...new Set(regions.map((r) => r.division).filter((d): d is string => Boolean(d)))],
    [regions],
  );
  const shown = regions.filter((r) => division === "all" || r.division === division);

  const selectedPrediction = byId.get(regionId);
  const selectedWeather = weatherById.get(regionId);
  const outlookPredictions = outlook
    .map((q) => q.data?.items.find((p) => p.region.id === regionId))
    .filter((p): p is PredictionOut => Boolean(p));
  const worstAhead = outlookPredictions.reduce<PredictionOut | undefined>(
    (worst, p) => (severity(p.risk_class) > severity(worst?.risk_class) ? p : worst),
    undefined,
  );

  // --- map layer -------------------------------------------------------------------------
  const scale: MapScale = useMemo(() => {
    if (layer === "risk")
      return { kind: "risk", label: `Predicted risk, ${forecastLabel(lead).toLowerCase()}` };
    const field = layer === "tmax" ? "tmax_c" : "temp_deviation_c";
    const values = (weather.data ?? []).map((w) => w[field]).filter((v): v is number => v !== null);
    const { min, max } = niceRange(values);
    return {
      kind: "sequential",
      label: layer === "tmax" ? "Forecast max temperature" : "Departure from seasonal normal",
      unit: "°C",
      min,
      max,
      format: (v: number) => formatFeatureValue(field, v),
      marks:
        layer === "tmax"
          ? [
              { value: 37, label: "Coastal threshold" },
              { value: 40, label: "Plains threshold" },
            ]
          : [
              { value: 4.5, label: "Heatwave departure" },
              { value: 6.5, label: "Severe departure" },
            ],
    };
  }, [layer, lead, weather.data]);

  const mapValues: Record<string, MapValue> = {};
  for (const place of regions) {
    const p = byId.get(place.id);
    const w = weatherById.get(place.id);
    const details = [
      p ? `${formatProbability(p.confidence)} confidence` : null,
      w?.tmax_c != null ? `Forecast ${formatFeatureValue("tmax_c", w.tmax_c)}` : null,
      w ? `Valid ${formatCalendarDate(w.date)}` : null,
      layer === "risk" && inlandCaveat(place) ? "Model not yet validated for inland places" : null,
    ].filter((d): d is string => Boolean(d));
    mapValues[place.id] = {
      risk: p?.risk_class ?? null,
      value:
        layer === "tmax"
          ? (w?.tmax_c ?? null)
          : layer === "departure"
            ? (w?.temp_deviation_c ?? null)
            : null,
      stale: Boolean(layer === "risk" ? p?.weather.stale : w?.provenance.stale),
      details,
    };
  }

  // --- freshness -------------------------------------------------------------------------
  const issuedAt = (weather.data ?? [])
    .map((w) => w.provenance.issued_at)
    .sort()
    .at(-1);
  const scoredAt = (snapshot.data?.items ?? [])
    .map((p) => p.created_at)
    .sort()
    .at(-1);
  const anyStale = (weather.data ?? []).some((w) => w.provenance.stale);
  const missing = snapshot.data?.missing_region_ids ?? [];

  async function scoreMissing() {
    try {
      const result = await score.mutateAsync();
      toast.success(
        result.scored
          ? `Scored ${result.scored} place-day pairs`
          : "Every place is already scored on the current forecast",
        { description: result.skipped ? `${result.skipped} already up to date` : undefined },
      );
    } catch (error) {
      toast.error("Scoring failed", { description: describeError(error).description });
    }
  }

  const toggleCompare = (id: string) =>
    setCompare((cur) =>
      cur.includes(id)
        ? cur.filter((x) => x !== id)
        : cur.length < MAX_COMPARE
          ? [...cur, id]
          : cur,
    );

  const rows = [...shown].sort(
    (a, b) =>
      severity(byId.get(b.id)?.risk_class) - severity(byId.get(a.id)?.risk_class) ||
      a.name.localeCompare(b.name),
  );

  return (
    <div className={cn(layout.page, layout.pageStack)}>
      <PageHeader
        title="Heatwave Command Center"
        subtitle="Climate intelligence for heatwave monitoring, prediction and early warning."
        context={
          <span className="inline-flex items-center gap-1 text-sm font-medium text-foreground">
            <MapPinned aria-hidden="true" className="size-4 text-muted-foreground" />
            {regionDisplayName(region, regionId)}
          </span>
        }
      />

      {/* --- Metric row (§2.2) --- */}
      <div className={cn(layout.grid, "sm:grid-cols-2 xl:grid-cols-4")}>
        <MetricCard
          label={`Max temperature · ${forecastLabel(lead)}`}
          icon={Thermometer}
          loading={weather.isPending}
          value={
            selectedWeather?.tmax_c != null
              ? formatFeatureValue("tmax_c", selectedWeather.tmax_c)
              : "—"
          }
          delta={
            selectedWeather?.temp_deviation_c != null
              ? {
                  text: `${formatFeatureValue("temp_deviation_c", selectedWeather.temp_deviation_c)} vs seasonal normal`,
                  direction:
                    selectedWeather.temp_deviation_c > 0
                      ? "up"
                      : selectedWeather.temp_deviation_c < 0
                        ? "down"
                        : "flat",
                  tone:
                    selectedWeather.temp_deviation_c >= 4.5
                      ? "danger"
                      : selectedWeather.temp_deviation_c > 0
                        ? "warning"
                        : "neutral",
                }
              : undefined
          }
          tags={selectedWeather?.provenance.stale ? <DataSourceTag kind="stale" /> : undefined}
        />
        <MetricCard
          label="Heatwave risk"
          icon={TriangleAlert}
          loading={snapshot.isPending}
          accent={
            selectedPrediction
              ? selectedPrediction.risk_class === "NORMAL"
                ? "success"
                : selectedPrediction.risk_class === "HEATWAVE"
                  ? "warning"
                  : "danger"
              : undefined
          }
          value={
            selectedPrediction ? (
              <RiskBadge riskClass={selectedPrediction.risk_class} size="lg" />
            ) : (
              "No prediction"
            )
          }
          subLabel={
            selectedPrediction
              ? `Valid ${formatCalendarDate(selectedPrediction.forecast_window.valid_date)}`
              : "Score places to see risk"
          }
        />
        <MetricCard
          label="Prediction confidence"
          icon={Gauge}
          loading={snapshot.isPending}
          value={selectedPrediction ? formatProbability(selectedPrediction.confidence) : "—"}
          subLabel={
            inlandCaveat(region ?? undefined)
              ? "Model not yet validated for inland places"
              : selectedPrediction
                ? "Probability of the predicted class"
                : undefined
          }
        />
        <MetricCard
          label="Forecast"
          icon={Droplets}
          loading={outlook.some((q) => q.isPending)}
          value="Next 1–3 Days"
          subLabel={
            worstAhead && worstAhead.risk_class !== "NORMAL"
              ? `Elevated heat risk: ${riskLabel(worstAhead.risk_class)} on ${formatCalendarDate(worstAhead.forecast_window.valid_date)}`
              : outlookPredictions.length
                ? "No elevated heat risk predicted"
                : "Not scored yet"
          }
        />
      </div>

      {/* --- Regional panel: Maharashtra map + table (§2.3, Part 11 R2.1) --- */}
      <Panel
        title="Maharashtra heatwave risk"
        description="Our selected monitoring places across the six divisions (a project selection, not an official list)."
        tags={anyStale ? <DataSourceTag kind="stale" /> : <DataSourceTag kind="live" />}
        action={
          <Button
            size="sm"
            variant={missing.length ? "default" : "outline"}
            onClick={() => void scoreMissing()}
            disabled={score.isPending}
          >
            <Sparkles aria-hidden="true" />
            {score.isPending
              ? "Scoring…"
              : missing.length
                ? `Score ${missing.length} places without a prediction`
                : "Score new forecasts"}
          </Button>
        }
        footer={
          <span className="flex flex-wrap gap-x-4 gap-y-1">
            <span>Forecast issued {issuedAt ? formatRelative(issuedAt) : "—"}</span>
            <span>Places scored {scoredAt ? formatRelative(scoredAt) : "—"}</span>
            {!env.inlandModelValidated && (
              <span>Inland (plains) predictions: model not yet validated for inland places.</span>
            )}
          </span>
        }
        contentClassName="flex flex-col gap-4"
      >
        <div className="flex flex-wrap items-center gap-2">
          <Segmented
            label="Forecast day"
            options={LEADS.map((l) => ({ id: l, label: forecastLabel(l) }))}
            value={lead}
            onChange={setLead}
          />
          <Segmented label="Map layer" options={LAYERS} value={layer} onChange={setLayer} />
          <label className="inline-flex items-center gap-2 text-xs text-muted-foreground">
            Division
            <select
              aria-label="Division"
              value={division}
              onChange={(e) => setDivision(e.target.value)}
              className="h-7 rounded-md border bg-card px-2 text-xs text-foreground"
            >
              <option value="all">All divisions</option>
              {divisions.map((d) => (
                <option key={d} value={d}>
                  {d}
                </option>
              ))}
            </select>
          </label>
        </div>

        {snapshot.isError && !snapshot.data ? (
          <ErrorState
            error={snapshot.error}
            onRetry={() => void snapshot.refetch()}
            retrying={snapshot.isFetching}
          />
        ) : snapshot.isPending || !regions.length ? (
          <LoadingState shape="chart" label="Loading the map" />
        ) : (
          <div className="grid gap-4 xl:grid-cols-5">
            <MaharashtraMap
              className="xl:col-span-3"
              places={shown}
              values={mapValues}
              scale={scale}
              selectedId={regionId}
              onSelect={setRegionId}
              title={`${scale.label}, ${forecastLabel(lead).toLowerCase()}, across Maharashtra`}
            />
            <div className="min-w-0 xl:col-span-2">
              {snapshot.data && snapshot.data.items.length === 0 ? (
                <EmptyState
                  title="No place has been scored yet"
                  description="Score the places to see predicted risk. Nothing is scored automatically when you open this page."
                />
              ) : null}
              <div className="relative overflow-x-auto">
                <table className="w-full min-w-[30rem] text-sm">
                  <caption className="sr-only">
                    Places, forecast and predicted risk, {forecastLabel(lead).toLowerCase()}
                  </caption>
                  <thead className="text-left text-xs text-muted-foreground">
                    <tr className="border-b">
                      <th className="w-8 py-2 font-medium">
                        <span className="sr-only">Compare</span>
                      </th>
                      <th className="py-2 font-medium">Place</th>
                      <th className="py-2 pl-3 text-right font-medium">Max</th>
                      <th className="py-2 pl-3 text-right font-medium">Δ normal</th>
                      <th className="py-2 pl-3 font-medium">Risk</th>
                      <th className="py-2 font-medium">
                        <span className="sr-only">Links</span>
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((place) => {
                      const p = byId.get(place.id);
                      const w: WeatherOut | undefined = weatherById.get(place.id);
                      const selected = place.id === regionId;
                      return (
                        <tr
                          key={place.id}
                          aria-selected={selected}
                          onClick={() => setRegionId(place.id)}
                          className={cn(
                            "cursor-pointer border-b last:border-0 hover:bg-muted/60",
                            selected && "bg-muted",
                          )}
                        >
                          <td className="py-1.5" onClick={(e) => e.stopPropagation()}>
                            <input
                              type="checkbox"
                              aria-label={`Compare ${place.name}`}
                              checked={compare.includes(place.id)}
                              disabled={
                                !compare.includes(place.id) && compare.length >= MAX_COMPARE
                              }
                              onChange={() => toggleCompare(place.id)}
                              className="size-3.5 accent-primary"
                            />
                          </td>
                          <td className="py-1.5">
                            <button
                              type="button"
                              className="text-left font-medium outline-none focus-visible:underline"
                              onClick={() => setRegionId(place.id)}
                            >
                              {place.name}
                            </button>
                            <span className="block text-xs text-muted-foreground">
                              {place.kind === "area" ? `${place.district} (area)` : place.district}
                            </span>
                          </td>
                          <td className="tabular py-1.5 pl-3 text-right whitespace-nowrap">
                            {w?.tmax_c != null ? formatFeatureValue("tmax_c", w.tmax_c) : "—"}
                          </td>
                          <td className="tabular py-1.5 pl-3 text-right whitespace-nowrap">
                            {w?.temp_deviation_c != null
                              ? formatFeatureValue("temp_deviation_c", w.temp_deviation_c)
                              : "—"}
                          </td>
                          <td className="py-1.5 pl-3">
                            {p ? (
                              <RiskBadge riskClass={p.risk_class} size="sm" />
                            ) : (
                              <span className="text-xs text-muted-foreground">Not scored</span>
                            )}
                          </td>
                          <td
                            className="py-1.5 pl-3 text-right whitespace-nowrap"
                            onClick={(e) => e.stopPropagation()}
                          >
                            <Link
                              to={withRegion("/predictions", place.id)}
                              className="text-xs font-medium text-primary underline-offset-2 hover:underline"
                            >
                              Details
                            </Link>
                            <span className="text-muted-foreground"> · </span>
                            <Link
                              to={withRegion("/analytics", place.id)}
                              className="text-xs font-medium text-primary underline-offset-2 hover:underline"
                            >
                              Analyse
                            </Link>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
              <div className="mt-3 flex items-center justify-between gap-2">
                <p className={typography.secondary}>
                  {compare.length
                    ? `${compare.length} of ${MAX_COMPARE} places selected to compare`
                    : "Tick up to 4 places to compare them."}
                </p>
                <Button
                  size="sm"
                  variant="outline"
                  disabled={compare.length < 2}
                  onClick={() => navigate(`/analytics?compare=${compare.join(",")}`)}
                >
                  <BarChart3 aria-hidden="true" /> Compare
                </Button>
              </div>
            </div>
          </div>
        )}
      </Panel>

      <div className={cn(layout.grid, "lg:grid-cols-2")}>
        {/* --- Why this prediction? (§2.4) --- */}
        <Panel
          title="Why this prediction?"
          description={
            selectedPrediction
              ? `${region?.name ?? regionId}, ${forecastLabel(lead).toLowerCase()}`
              : undefined
          }
          tags={<DataSourceTag kind="ai" />}
          action={
            <Button asChild variant="ghost" size="sm">
              <Link to={withRegion("/predictions", regionId)}>
                <Brain aria-hidden="true" /> Full explanation
              </Link>
            </Button>
          }
        >
          {selectedPrediction ? (
            <div className="flex flex-col gap-4">
              <FactorList
                factors={selectedPrediction.explanation.factors}
                limit={3}
                fitScale
                showValue={false}
              />
              <p className={typography.secondary}>{selectedPrediction.explanation.summary}</p>
            </div>
          ) : snapshot.isPending ? (
            <LoadingState shape="factors" rows={3} />
          ) : (
            <EmptyState
              title="No prediction for this place yet"
              description="Score the places to see the model's reasons."
            />
          )}
        </Panel>

        {/* --- Recommended authority actions (§2.5) --- */}
        <Panel title="Recommended Authority Actions" tags={<DataSourceTag kind="act" />}>
          {selectedPrediction ? (
            <ActionList actions={selectedPrediction.recommended_actions} limit={5} />
          ) : snapshot.isPending ? (
            <LoadingState shape="list" rows={3} />
          ) : (
            <EmptyState
              icon={ListChecks}
              title="No actions yet"
              description="Actions follow from the place's prediction."
            />
          )}
        </Panel>
      </div>
    </div>
  );
}
