/**
 * Style guide / component showcase (Part 10 §7): every token and shared component, rendered in
 * isolation with contract-shaped sample data, so inconsistencies show up before Parts 11–14.
 * Route: /design-system (linked from the account menu).
 */
import { Activity, Droplets, Gauge, Thermometer, Wind } from "lucide-react";
import type { ReactNode } from "react";
import { ActionList } from "@/components/shared/action-list";
import { FactorList } from "@/components/shared/contributing-factor-bar";
import {
  DataSourceTag,
  DATA_SOURCE_PRESETS,
  type DataSourceKind,
} from "@/components/shared/data-source-tag";
import { MetricCard } from "@/components/shared/metric-card";
import { PageHeader, Panel } from "@/components/shared/panel";
import { ProtectedAction } from "@/components/shared/protected-action";
import { RiskBadge } from "@/components/shared/risk-badge";
import { EmptyState, ErrorState, LoadingState } from "@/components/shared/states";
import { StatusPill } from "@/components/shared/status-pill";
import { Button } from "@/components/ui/button";
import { SAMPLE_ALERT, SAMPLE_PREDICTION } from "@/design/fixtures";
import { formatFeatureValue, formatProbability, RISK_CLASSES, riskLabel } from "@/design/labels";
import {
  layout,
  OPERATIONAL_STATUSES,
  RISK_TONE,
  STATUS_TONE,
  TONE_STYLE,
  typography,
  type Tone,
} from "@/design/tokens";
import { ApiError } from "@/lib/api/errors";
import { cn } from "@/lib/utils";

const SECTIONS = [
  ["colour", "Colour semantics"],
  ["type", "Typography & spacing"],
  ["risk-badge", "Risk badge"],
  ["status-pill", "Status pill"],
  ["metric-card", "Metric card"],
  ["factors", "Contributing-factor bar"],
  ["tags", "Data-source tag"],
  ["actions", "Action list"],
  ["states", "Loading, error & empty"],
] as const;

function Section({
  id,
  title,
  intro,
  children,
}: {
  id: string;
  title: string;
  intro?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section id={id} aria-labelledby={`${id}-title`} className="flex scroll-mt-28 flex-col gap-4">
      <div className="flex flex-col gap-1">
        <h2 id={`${id}-title`} className="text-lg font-semibold tracking-tight">
          {title}
        </h2>
        {intro && <p className={cn(typography.secondary, "max-w-3xl")}>{intro}</p>}
      </div>
      {children}
    </section>
  );
}

const TONE_ROLE: Record<Tone, string> = {
  success: "Normal · success · READY / NOTIFIED",
  warning: "Heatwave · warning · PENDING · raises-risk factor",
  danger: "Severe Heatwave · critical · FAILED · brand accent",
  info: "AI-derived · ISSUED · lowers-risk factor",
  neutral: "Chrome · DRAFT · demo data",
};

function Swatch({ tone }: { tone: Tone }) {
  const style = TONE_STYLE[tone];
  return (
    <div className="flex flex-col overflow-hidden rounded-xl border bg-card">
      <div className={cn("flex h-16 items-end p-3 text-sm font-semibold", style.solid)}>{tone}</div>
      <div className={cn("border-t px-3 py-2 text-xs font-medium", style.subtle)}>
        Subtle surface · text
      </div>
      <p className="px-3 py-2 text-xs text-muted-foreground">{TONE_ROLE[tone]}</p>
    </div>
  );
}

export function DesignSystemPage() {
  const p = SAMPLE_PREDICTION;
  return (
    <div className={cn(layout.page, "lg:grid lg:grid-cols-[13rem_minmax(0,1fr)] lg:gap-10")}>
      <aside className="hidden lg:block">
        <nav
          aria-label="Design system sections"
          className="sticky top-24 flex flex-col gap-1 text-sm"
        >
          {SECTIONS.map(([id, title]) => (
            <a
              key={id}
              href={`#${id}`}
              className="rounded-md px-2 py-1 text-muted-foreground hover:bg-accent hover:text-foreground"
            >
              {title}
            </a>
          ))}
        </nav>
      </aside>

      <div className="flex min-w-0 flex-col gap-12">
        <PageHeader
          title="Design system"
          subtitle="Tokens and shared components for Parts 11–14. Import these; never re-implement them per page."
          context={<DataSourceTag kind="demo" />}
        />

        <Section
          id="colour"
          title="Colour semantics"
          intro={
            <>
              One mapping from risk class to colour, defined once in{" "}
              <code>src/styles/globals.css</code> and <code>src/design/tokens.ts</code>. Colour is
              always paired with the class name and an icon.
            </>
          }
        >
          <div className="grid gap-3 sm:grid-cols-3">
            {RISK_CLASSES.map((rc) => (
              <div
                key={rc}
                className="flex items-center justify-between rounded-xl border bg-card p-4"
              >
                <div className="flex flex-col gap-0.5">
                  <span className="text-sm font-semibold">{riskLabel(rc)}</span>
                  <code className="text-xs text-muted-foreground">
                    {rc} → {RISK_TONE[rc]}
                  </code>
                </div>
                <RiskBadge riskClass={rc} variant="solid" />
              </div>
            ))}
          </div>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
            {(Object.keys(TONE_STYLE) as Tone[]).map((tone) => (
              <Swatch key={tone} tone={tone} />
            ))}
          </div>
        </Section>

        <Section
          id="type"
          title="Typography & spacing"
          intro="Inter, one type scale by role. A 4 px spacing unit; cards pad 20 px and gap 16 px."
        >
          <div className="flex flex-col gap-4 rounded-xl border bg-card p-5">
            {(
              [
                ["pageTitle", "Heatwave Command Center"],
                [
                  "pageSubtitle",
                  "Climate intelligence for heatwave monitoring, prediction and early warning.",
                ],
                ["sectionTitle", "Regional Heatwave Risk"],
                ["cardTitle", "Current Temperature"],
                ["metricValue", "42.6 °C"],
                ["body", "Residents are advised to avoid prolonged outdoor exposure."],
                ["meta", "Demo data"],
              ] as const
            ).map(([role, sample]) => (
              <div
                key={role}
                className="grid gap-1 sm:grid-cols-[12rem_minmax(0,1fr)] sm:items-baseline sm:gap-4"
              >
                <code className="text-xs text-muted-foreground">typography.{role}</code>
                <span className={typography[role]}>{sample}</span>
              </div>
            ))}
          </div>
        </Section>

        <Section
          id="risk-badge"
          title="Risk badge"
          intro="Dashboard regional table, prediction banner, alerts list."
        >
          <div className="flex flex-col gap-3 rounded-xl border bg-card p-5">
            {(["subtle", "solid"] as const).map((variant) => (
              <div key={variant} className="flex flex-wrap items-center gap-3">
                <code className="w-14 text-xs text-muted-foreground">{variant}</code>
                {RISK_CLASSES.map((rc) => (
                  <RiskBadge key={rc} riskClass={rc} variant={variant} />
                ))}
                <RiskBadge riskClass="SEVERE_HEATWAVE" variant={variant} size="sm" />
                <RiskBadge riskClass="SEVERE_HEATWAVE" variant={variant} size="lg" />
              </div>
            ))}
          </div>
        </Section>

        <Section
          id="status-pill"
          title="Status pill"
          intro="Alert and delivery status, sharing the risk semantics. Pills with a detail (hover or focus) carry the API's reason."
        >
          <div className="flex flex-col gap-4 rounded-xl border bg-card p-5">
            <div className="flex flex-wrap items-center gap-3">
              {OPERATIONAL_STATUSES.map((s) => (
                <div key={s} className="flex flex-col items-start gap-1">
                  <StatusPill status={s} />
                  <code className="text-[0.625rem] text-muted-foreground">{STATUS_TONE[s]}</code>
                </div>
              ))}
            </div>
            <ul className="divide-y rounded-lg border">
              {SAMPLE_ALERT.channels.map((c) => (
                <li
                  key={c.channel}
                  className="flex items-center justify-between gap-3 px-3 py-2 text-sm"
                >
                  {c.label}
                  <StatusPill status={c.status} detail={c.status === "FAILED" ? c.detail : null} />
                </li>
              ))}
            </ul>
          </div>
        </Section>

        <Section
          id="metric-card"
          title="Metric card"
          intro="Values come straight from API fields, formatted with the shared label table."
        >
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <MetricCard
              label="Current Temperature"
              icon={Thermometer}
              value={formatFeatureValue("tmax_c", p.inputs.tmax_c)}
              delta={{
                text: `${formatFeatureValue("temp_deviation_c", p.inputs.temp_deviation_c)} above seasonal normal`,
                direction: "up",
                tone: "danger",
              }}
              tags={<DataSourceTag kind="demo" />}
            />
            <MetricCard
              label="Heatwave Risk"
              icon={Activity}
              accent={RISK_TONE[p.risk_class]}
              value={<RiskBadge riskClass={p.risk_class} size="lg" />}
              subLabel={`${formatProbability(p.confidence)} predicted probability`}
            />
            <MetricCard
              label="Prediction Confidence"
              icon={Gauge}
              value={formatProbability(p.confidence)}
              subLabel="Model confidence in this class"
            />
            <MetricCard
              label="Relative Humidity"
              icon={Droplets}
              value={formatFeatureValue("rh_pct", p.inputs.rh_pct)}
              subLabel="Missing reading"
            />
            <MetricCard label="Wind Speed" icon={Wind} value="" loading />
          </div>
        </Section>

        <Section
          id="factors"
          title="Contributing-factor bar"
          intro="Consumes Part 06's factors unchanged. Bars diverge from the centre: right raises risk, left lowers it. Note Wind Speed (protective, negative) and the estimated humidity reading."
        >
          <div className="grid gap-4 lg:grid-cols-2">
            <Panel
              title="Why did the AI make this prediction?"
              tags={
                <>
                  <DataSourceTag kind="ai" />
                  <DataSourceTag kind="demo" />
                </>
              }
            >
              <div className="flex flex-col gap-5">
                <FactorList factors={p.explanation.factors} />
                <p className={cn(typography.secondary, "border-l-2 border-tone-info-border pl-3")}>
                  {p.explanation.summary}
                </p>
              </div>
            </Panel>
            <Panel
              title="Why this prediction?"
              description="Condensed (dashboard): top 3, scaled to fit."
              tags={<DataSourceTag kind="ai" />}
            >
              <FactorList factors={p.explanation.factors} limit={3} fitScale showValue={false} />
            </Panel>
          </div>
        </Section>

        <Section
          id="tags"
          title="Data-source tag"
          intro="Presets keep wording consistent; label, tone and icon are configurable."
        >
          <div className="flex flex-wrap items-center gap-2 rounded-xl border bg-card p-5">
            {(Object.keys(DATA_SOURCE_PRESETS) as DataSourceKind[]).map((kind) => (
              <DataSourceTag key={kind} kind={kind} />
            ))}
          </div>
        </Section>

        <Section
          id="actions"
          title="Action list"
          intro="Recommended authority actions, in the API's deterministic order (RA-v1)."
        >
          <Panel
            title="Recommended Authority Actions"
            tags={<DataSourceTag kind="act" />}
            action={
              <ProtectedAction label="Sign in to issue">
                <Button size="sm">Issue Warning</Button>
              </ProtectedAction>
            }
          >
            <ActionList actions={p.recommended_actions} />
          </Panel>
        </Section>

        <Section
          id="states"
          title="Loading, error & empty"
          intro="The default for every data-driven card, via <QueryState>."
        >
          <div className="grid gap-4 lg:grid-cols-3">
            <Panel title="Loading">
              <div className="flex flex-col gap-6">
                <LoadingState shape="factors" rows={3} />
                <LoadingState shape="list" rows={2} />
              </div>
            </Panel>
            <Panel title="Error">
              <ErrorState
                error={
                  new ApiError({
                    kind: "upstream",
                    code: "WEATHER_DATA_UNAVAILABLE",
                    message: "",
                    status: 503,
                    requestId: "c2353ec933024868", // pragma: allowlist secret (a sample request id)
                  })
                }
                onRetry={() => undefined}
              />
            </Panel>
            <Panel title="Empty">
              <EmptyState
                title="No alerts issued yet"
                description="Alerts you create or issue for this region will appear here."
                action={
                  <Button size="sm" variant="outline">
                    Create alert
                  </Button>
                }
              />
            </Panel>
          </div>
          <Panel title="Compact error (metric cards, nav)">
            <ErrorState
              error={
                new ApiError({ kind: "network", code: "NETWORK_ERROR", message: "", status: 0 })
              }
              onRetry={() => undefined}
              compact
            />
          </Panel>
        </Section>
      </div>
    </div>
  );
}
