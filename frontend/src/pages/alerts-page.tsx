/**
 * Heatwave Early Warning (Part 13 + R2; the teacher's M5: alerts on Node.js + MongoDB).
 *
 * Frozen scope: the alert list (entry point), a new-alert form pre-filled from the selected
 * place's latest prediction, Save as Draft / Issue Warning (with a confirmation step), and a
 * detail view whose channel statuses poll until delivery finishes. Delivery is mock: the API
 * records each channel as delivered and sends nothing (labelled on screen).
 */
import { BellRing, MapPinned, Plus, Send } from "lucide-react";
import { useMemo, useState, type FormEvent } from "react";
import { Link } from "react-router";
import { toast } from "sonner";
import { PageHeader, Panel } from "@/components/shared/panel";
import { RiskBadge } from "@/components/shared/risk-badge";
import { EmptyState, LoadingState, QueryState } from "@/components/shared/states";
import { StatusPill } from "@/components/shared/status-pill";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { riskLabel } from "@/design/labels";
import { layout, typography } from "@/design/tokens";
import { describeError } from "@/lib/api/errors";
import type { AlertOut, AlertSeverity } from "@/lib/api/types";
import { formatDateTime, formatCalendarDate } from "@/lib/format";
import {
  useAlert,
  useAlertChannels,
  useAlerts,
  useCreateAlert,
  useLatestPrediction,
  useUpdateAlert,
} from "@/lib/query/hooks";
import { cn } from "@/lib/utils";
import { regionDisplayName, useRegion, withRegion } from "@/state/region-context";

/** The advisory template (config/notification_templates.yaml wording; editable before issuing). */
function advisory(severity: AlertSeverity, place: string): string {
  const head = severity === "SEVERE_HEATWAVE" ? "SEVERE HEATWAVE ALERT" : "HEATWAVE ALERT";
  return `${head} - ${place.toUpperCase()}: ${
    severity === "SEVERE_HEATWAVE" ? "Severe heatwave expected." : "Heatwave conditions expected."
  } Avoid prolonged outdoor exposure between 12 PM and 4 PM, stay hydrated and check on elderly neighbours.`;
}

function NewAlertForm({ onCreated }: { onCreated: (id: string) => void }) {
  const { regionId, region } = useRegion();
  const latest = useLatestPrediction(regionId, { leadDays: 0 });
  const channels = useAlertChannels();
  const create = useCreateAlert();
  const predicted = latest.data?.risk_class;
  const suggested: AlertSeverity = predicted === "SEVERE_HEATWAVE" ? "SEVERE_HEATWAVE" : "HEATWAVE";
  const [severity, setSeverity] = useState<AlertSeverity | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [selected, setSelected] = useState<string[] | null>(null);
  const [confirming, setConfirming] = useState(false);
  // One id per form: a double submit returns the same alert instead of a second one.
  const [requestId] = useState(() => crypto.randomUUID());

  const sev = severity ?? suggested;
  const text = message ?? advisory(sev, region?.name ?? regionId);
  const chosen = selected ?? (channels.data ?? []).map((c) => c.id);

  async function submit(status: "DRAFT" | "ISSUED") {
    try {
      const alert = await create.mutateAsync({
        client_request_id: requestId,
        region_id: regionId,
        severity: sev,
        message: text,
        channels: chosen,
        status,
        prediction_id: latest.data?.prediction_id ?? null,
      });
      toast.success(
        status === "ISSUED" ? `Warning ${alert.alert_id} issued` : `Draft ${alert.alert_id} saved`,
      );
      onCreated(alert.alert_id);
    } catch (error) {
      toast.error("The alert was not saved", { description: describeError(error).description });
    } finally {
      setConfirming(false);
    }
  }

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    void submit("DRAFT");
  };

  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-4" aria-label="New alert">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <MapPinned aria-hidden="true" className="size-4 text-muted-foreground" />
        <span className="font-medium">{regionDisplayName(region, regionId)}</span>
        <span className="text-muted-foreground">(change the place in the top bar)</span>
      </div>
      <p className={typography.secondary}>
        {latest.data ? (
          <>
            Latest prediction today:{" "}
            <Link
              className="font-medium text-primary underline-offset-2 hover:underline"
              to={withRegion("/predictions", regionId)}
            >
              {riskLabel(latest.data.risk_class)}
            </Link>{" "}
            for {formatCalendarDate(latest.data.forecast_window.valid_date)}. It will be linked to
            this alert.
          </>
        ) : (
          "No prediction for this place today; the alert is created without one."
        )}
      </p>
      <fieldset className="flex flex-col gap-2">
        <legend className="mb-1 text-sm font-medium">Severity</legend>
        <div className="flex gap-2">
          {(["HEATWAVE", "SEVERE_HEATWAVE"] as const).map((s) => (
            <label
              key={s}
              className={cn(
                "flex cursor-pointer items-center gap-2 rounded-md border px-3 py-1.5 text-sm",
                sev === s && "border-ring bg-muted",
              )}
            >
              <input
                type="radio"
                name="severity"
                value={s}
                checked={sev === s}
                onChange={() => {
                  setSeverity(s);
                  if (message === null) setMessage(null);
                }}
                className="accent-primary"
              />
              {riskLabel(s)}
            </label>
          ))}
        </div>
      </fieldset>
      <div className="flex flex-col gap-2">
        <Label htmlFor="advisory">Public advisory</Label>
        <textarea
          id="advisory"
          value={text}
          onChange={(e) => setMessage(e.target.value)}
          rows={4}
          maxLength={1000}
          className="rounded-md border bg-card px-3 py-2 text-sm"
        />
        <span className="text-xs text-muted-foreground">
          {text.trim().length} / 1000 characters (at least 10)
        </span>
      </div>
      <fieldset className="flex flex-col gap-2">
        <legend className="mb-1 text-sm font-medium">Distribution channels</legend>
        {channels.isPending ? (
          <LoadingState shape="lines" rows={3} />
        ) : (
          <div className="grid gap-1.5 sm:grid-cols-2">
            {(channels.data ?? []).map((c) => (
              <label key={c.id} className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={chosen.includes(c.id)}
                  onChange={() =>
                    setSelected(
                      chosen.includes(c.id) ? chosen.filter((x) => x !== c.id) : [...chosen, c.id],
                    )
                  }
                  className="accent-primary"
                />
                {c.label} <span className="text-xs text-muted-foreground">({c.mechanism})</span>
              </label>
            ))}
          </div>
        )}
      </fieldset>
      <div className="flex flex-wrap items-center gap-2">
        <Button
          type="submit"
          variant="outline"
          disabled={create.isPending || chosen.length === 0 || text.trim().length < 10}
        >
          Save as Draft
        </Button>
        {!confirming ? (
          <Button
            type="button"
            onClick={() => setConfirming(true)}
            disabled={create.isPending || chosen.length === 0 || text.trim().length < 10}
          >
            <Send aria-hidden="true" /> Issue Warning
          </Button>
        ) : (
          <span
            role="alertdialog"
            aria-label="Confirm issue"
            className="flex flex-wrap items-center gap-2 rounded-md border border-tone-danger-border bg-tone-danger-subtle px-3 py-1.5 text-sm text-tone-danger-subtle-fg"
          >
            Issue to {chosen.length} channel{chosen.length === 1 ? "" : "s"}? This cannot be undone.
            <Button
              type="button"
              size="sm"
              variant="destructive"
              onClick={() => void submit("ISSUED")}
              disabled={create.isPending}
            >
              Confirm issue
            </Button>
            <Button type="button" size="sm" variant="ghost" onClick={() => setConfirming(false)}>
              Cancel
            </Button>
          </span>
        )}
      </div>
    </form>
  );
}

function AlertDetail({ alertId }: { alertId: string }) {
  const query = useAlert(alertId);
  const update = useUpdateAlert();
  const [confirming, setConfirming] = useState(false);

  async function issue() {
    try {
      await update.mutateAsync({ alertId, changes: { status: "ISSUED" } });
      toast.success(`Warning ${alertId} issued`);
    } catch (error) {
      toast.error("The alert was not issued", { description: describeError(error).description });
    } finally {
      setConfirming(false);
    }
  }

  return (
    <QueryState query={query} loading={<LoadingState shape="list" rows={4} />}>
      {(a: AlertOut) => (
        <div className="flex flex-col gap-4">
          <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
            <dt className="text-muted-foreground">Alert ID</dt>
            <dd className="font-mono">{a.alert_id}</dd>
            <dt className="text-muted-foreground">Status</dt>
            <dd>
              <StatusPill status={a.status} />
            </dd>
            <dt className="text-muted-foreground">Severity</dt>
            <dd>
              <RiskBadge riskClass={a.severity} size="sm" />
            </dd>
            <dt className="text-muted-foreground">Target place</dt>
            <dd>{a.region.name}</dd>
            <dt className="text-muted-foreground">Created</dt>
            <dd>{formatDateTime(a.created_at)}</dd>
            <dt className="text-muted-foreground">Issued</dt>
            <dd>{a.issued_at ? formatDateTime(a.issued_at) : "Not issued"}</dd>
          </dl>
          <blockquote className="rounded-md border-l-4 border-tone-warning-border bg-muted px-3 py-2 text-sm">
            {a.message}
          </blockquote>
          <div className="flex flex-col gap-2">
            <h3 className="text-sm font-medium">Distribution</h3>
            <ul className="flex flex-col gap-1.5">
              {a.channels.map((c) => (
                <li
                  key={c.channel}
                  className="flex flex-wrap items-center justify-between gap-2 text-sm"
                >
                  <span>{c.label}</span>
                  <span className="flex items-center gap-2">
                    {c.detail && <span className="text-xs text-muted-foreground">{c.detail}</span>}
                    <StatusPill status={c.status} detail={c.detail} />
                  </span>
                </li>
              ))}
            </ul>
            {a.status === "ISSUED" && (
              <p className="text-xs text-muted-foreground">
                {a.delivery_summary.pending > 0
                  ? `Delivering… ${a.delivery_summary.notified} of ${a.delivery_summary.total} done (refreshes automatically)`
                  : `${a.delivery_summary.notified} of ${a.delivery_summary.total} channels notified. Mock delivery: recorded only, no real SMS or e-mail was sent.`}
              </p>
            )}
          </div>
          {a.status !== "ISSUED" &&
            (!confirming ? (
              <Button
                className="w-fit"
                onClick={() => setConfirming(true)}
                disabled={update.isPending}
              >
                <Send aria-hidden="true" /> Issue Warning
              </Button>
            ) : (
              <span
                role="alertdialog"
                aria-label="Confirm issue"
                className="flex flex-wrap items-center gap-2 text-sm"
              >
                Issue {a.alert_id}? This cannot be undone.
                <Button
                  size="sm"
                  variant="destructive"
                  onClick={() => void issue()}
                  disabled={update.isPending}
                >
                  Confirm issue
                </Button>
                <Button size="sm" variant="ghost" onClick={() => setConfirming(false)}>
                  Cancel
                </Button>
              </span>
            ))}
        </div>
      )}
    </QueryState>
  );
}

export function AlertsPage() {
  const { regionId, region } = useRegion();
  const list = useAlerts({ limit: 25 });
  const [selected, setSelected] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const current = useMemo(
    () => selected ?? list.data?.alerts[0]?.alert_id ?? null,
    [selected, list.data],
  );

  return (
    <div className={cn(layout.page, layout.pageStack)}>
      <PageHeader
        title="Heatwave Early Warning"
        subtitle="Alert creation and authority response management"
        context={<span className="text-sm font-medium">{regionDisplayName(region, regionId)}</span>}
        actions={
          <Button size="sm" onClick={() => setCreating(true)}>
            <Plus aria-hidden="true" /> New alert
          </Button>
        }
      />
      <div className={cn(layout.grid, "lg:grid-cols-5")}>
        <Panel
          className="lg:col-span-3"
          title="Alerts"
          description="Newest first. Select one to see its distribution status."
        >
          <QueryState
            query={list}
            loading={<LoadingState shape="list" rows={4} />}
            isEmpty={(d) => d.alerts.length === 0}
            empty={
              <EmptyState
                icon={BellRing}
                title="No alerts yet"
                description="Create the first one with New alert."
              />
            }
          >
            {(d) => (
              <div className="overflow-x-auto">
                <table className="w-full min-w-[34rem] text-sm">
                  <caption className="sr-only">Alerts</caption>
                  <thead className="text-left text-xs text-muted-foreground">
                    <tr className="border-b">
                      <th className="py-1.5 font-medium">ID</th>
                      <th className="py-1.5 pl-3 font-medium">Place</th>
                      <th className="py-1.5 pl-3 font-medium">Severity</th>
                      <th className="py-1.5 pl-3 font-medium">Status</th>
                      <th className="py-1.5 pl-3 font-medium">Created</th>
                    </tr>
                  </thead>
                  <tbody>
                    {d.alerts.map((a) => (
                      <tr
                        key={a.alert_id}
                        aria-selected={a.alert_id === current && !creating}
                        onClick={() => {
                          setSelected(a.alert_id);
                          setCreating(false);
                        }}
                        className={cn(
                          "cursor-pointer border-b last:border-0 hover:bg-muted/60",
                          a.alert_id === current && !creating && "bg-muted",
                        )}
                      >
                        <td className="py-1.5">
                          <button
                            type="button"
                            className="font-mono"
                            onClick={() => {
                              setSelected(a.alert_id);
                              setCreating(false);
                            }}
                          >
                            {a.alert_id}
                          </button>
                        </td>
                        <td className="py-1.5 pl-3">{a.region.name}</td>
                        <td className="py-1.5 pl-3">
                          <RiskBadge riskClass={a.severity} size="sm" />
                        </td>
                        <td className="py-1.5 pl-3">
                          <StatusPill status={a.status} />
                        </td>
                        <td className="py-1.5 pl-3 whitespace-nowrap">
                          {formatDateTime(a.created_at)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </QueryState>
        </Panel>
        <Panel className="lg:col-span-2" title={creating ? "New alert" : "Alert details"}>
          {creating ? (
            <NewAlertForm
              onCreated={(id) => {
                setSelected(id);
                setCreating(false);
              }}
            />
          ) : current ? (
            <AlertDetail alertId={current} />
          ) : (
            <EmptyState title="No alert selected" />
          )}
        </Panel>
      </div>
    </div>
  );
}
