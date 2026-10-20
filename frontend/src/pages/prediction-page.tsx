/**
 * Heatwave Prediction (Part 12 + R2): one place's latest stored prediction, fully explained.
 * Every number is a field of the API's PredictionOut (inputs, probabilities, SHAP factors);
 * nothing is recomputed here. "Recompute" asks the ML service (through the Node API) for a new
 * prediction explicitly; opening the page never does.
 */
import { Droplets, MapPinned, RotateCw, Thermometer, TrendingUp, Wind } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { ActionList } from "@/components/shared/action-list";
import { FactorList } from "@/components/shared/contributing-factor-bar";
import { DataSourceTag } from "@/components/shared/data-source-tag";
import { MetricCard } from "@/components/shared/metric-card";
import { PageHeader, Panel } from "@/components/shared/panel";
import { RiskBadge } from "@/components/shared/risk-badge";
import { EmptyState, QueryState } from "@/components/shared/states";
import { Button } from "@/components/ui/button";
import { formatFeatureValue, formatProbability } from "@/design/labels";
import { RISK_TONE, TONE_STYLE, layout, typography } from "@/design/tokens";
import { describeError } from "@/lib/api/errors";
import type { PredictionOut } from "@/lib/api/types";
import { env } from "@/lib/env";
import { formatCalendarDate, formatRelative, forecastLabel } from "@/lib/format";
import { useLatestPrediction, useRecomputePrediction } from "@/lib/query/hooks";
import { cn } from "@/lib/utils";
import { regionDisplayName, useRegion } from "@/state/region-context";

const LEADS = [0, 1, 2, 3];

function Banner({ p, inland }: { p: PredictionOut; inland: boolean }) {
  const tone = TONE_STYLE[RISK_TONE[p.risk_class]];
  return (
    <section
      aria-label="Predicted risk"
      className={cn(
        "flex flex-wrap items-center justify-between gap-4 rounded-xl border-2 bg-card p-6",
        tone.border,
      )}
    >
      <div className="flex flex-col gap-2">
        <RiskBadge riskClass={p.risk_class} size="lg" variant="solid" />
        <p className="text-lg font-semibold">
          {p.region.name}, {forecastLabel(p.forecast_window.lead_days).toLowerCase()} (
          {formatCalendarDate(p.forecast_window.valid_date)})
        </p>
        <p className={typography.secondary}>
          Forecast window: next 1–3 days · predicted {formatRelative(p.created_at)} from the
          forecast issued {formatRelative(p.forecast_window.issued_at)}
        </p>
        {inland && (
          <p className="text-sm font-medium text-tone-warning-subtle-fg">
            Model not yet validated for inland places: treat this as indicative and check the
            temperatures below.
          </p>
        )}
      </div>
      <div className="text-right">
        <p className={cn(typography.metricValue)}>{formatProbability(p.confidence)}</p>
        <p className={typography.secondary}>Probability of the predicted class</p>
      </div>
    </section>
  );
}

export function PredictionPage() {
  const { regionId, region } = useRegion();
  const [lead, setLead] = useState(0);
  const query = useLatestPrediction(regionId, { leadDays: lead });
  const recompute = useRecomputePrediction();
  const inland = Boolean(region && region.zone !== "coastal" && !env.inlandModelValidated);

  async function onRecompute() {
    try {
      await recompute.mutateAsync({ regionId, leadDays: lead });
      toast.success("New prediction stored");
    } catch (error) {
      toast.error("Could not compute a new prediction", {
        description: describeError(error).description,
      });
    }
  }

  return (
    <div className={cn(layout.page, layout.pageStack)}>
      <PageHeader
        title="Heatwave Prediction"
        subtitle="AI-powered short-term heatwave risk assessment"
        context={
          <span className="inline-flex items-center gap-1 text-sm font-medium">
            <MapPinned aria-hidden="true" className="size-4 text-muted-foreground" />
            {regionDisplayName(region, regionId)}
          </span>
        }
        actions={
          <>
            <div
              role="group"
              aria-label="Forecast day"
              className="inline-flex flex-wrap rounded-lg border bg-muted p-0.5"
            >
              {LEADS.map((l) => (
                <button
                  key={l}
                  type="button"
                  aria-pressed={l === lead}
                  onClick={() => setLead(l)}
                  className={cn(
                    "h-7 rounded-md px-2.5 text-xs font-medium text-muted-foreground",
                    l === lead && "bg-card text-foreground shadow-xs",
                  )}
                >
                  {forecastLabel(l)}
                </button>
              ))}
            </div>
            <Button
              size="sm"
              variant="outline"
              onClick={() => void onRecompute()}
              disabled={recompute.isPending}
            >
              <RotateCw aria-hidden="true" className={cn(recompute.isPending && "animate-spin")} />
              {recompute.isPending ? "Computing…" : "Recompute"}
            </Button>
          </>
        }
      />

      <QueryState
        query={query}
        notFoundAsEmpty
        empty={
          <EmptyState
            title="No prediction for this place and day yet"
            description="Use Recompute to ask the model, or score all places from the dashboard."
          />
        }
      >
        {(p) => (
          <div className="flex flex-col gap-6">
            <Banner p={p} inland={inland} />

            <div className={cn(layout.grid, "sm:grid-cols-2 xl:grid-cols-4")}>
              <MetricCard
                label="Maximum Temperature"
                icon={Thermometer}
                value={formatFeatureValue("tmax_c", p.inputs.tmax_c)}
                subLabel={`Seasonal normal ${formatFeatureValue("normal_tmax_c", p.inputs.normal_tmax_c)}`}
              />
              <MetricCard
                label="Relative Humidity"
                icon={Droplets}
                value={formatFeatureValue("rh_pct", p.inputs.rh_pct)}
              />
              <MetricCard
                label="Wind Speed"
                icon={Wind}
                value={formatFeatureValue("wind_ms", p.inputs.wind_ms)}
                subLabel="at 2 m"
              />
              <MetricCard
                label="Temperature Deviation"
                icon={TrendingUp}
                value={formatFeatureValue("temp_deviation_c", p.inputs.temp_deviation_c)}
                subLabel="vs seasonal normal"
              />
            </div>

            <div className={cn(layout.grid, "lg:grid-cols-5")}>
              <Panel
                className="lg:col-span-3"
                title="Why did the AI make this prediction?"
                tags={
                  <>
                    <DataSourceTag kind="ai" />
                    {p.weather.stale && <DataSourceTag kind="stale" />}
                  </>
                }
                footer={`Model ${p.explanation.model_version} · explainer ${p.explanation.explainer_id}`}
              >
                <div className="flex flex-col gap-5">
                  <FactorList factors={p.explanation.factors} />
                  <p className={typography.body}>{p.explanation.summary}</p>
                </div>
              </Panel>
              <Panel
                className="lg:col-span-2"
                title="Recommended Authority Response"
                tags={<DataSourceTag kind="act" />}
              >
                <ActionList actions={p.recommended_actions} />
              </Panel>
            </div>
          </div>
        )}
      </QueryState>
    </div>
  );
}
