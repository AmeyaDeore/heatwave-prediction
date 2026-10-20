import { ArrowDownRight, ArrowUpRight, Minus, type LucideIcon } from "lucide-react";
import type { ReactNode } from "react";
import { Skeleton } from "@/components/ui/skeleton";
import { TONE_STYLE, typography, type Tone } from "@/design/tokens";
import { cn } from "@/lib/utils";

export interface MetricDelta {
  /** Display text as it should read, e.g. "+3.0 °C above seasonal normal". */
  text: string;
  direction?: "up" | "down" | "flat";
  /** Colour meaning: for heat, "up" is usually bad (warning/danger), not "success". */
  tone?: Tone;
}

export interface MetricCardProps {
  label: string;
  /** The big value: a string, a number already formatted, or a node such as a RiskBadge. */
  value: ReactNode;
  unit?: string;
  delta?: MetricDelta;
  /** Secondary line under the value, e.g. "Predicted probability". */
  subLabel?: ReactNode;
  icon?: LucideIcon;
  /** DataSourceTag(s) for the card's top-right corner. */
  tags?: ReactNode;
  /** Accent the card's left edge with a tone (e.g. the risk card). */
  accent?: Tone;
  loading?: boolean;
  className?: string;
}

const DELTA_ICON = { up: ArrowUpRight, down: ArrowDownRight, flat: Minus } as const;
const ACCENT = {
  success: "before:bg-tone-success",
  warning: "before:bg-tone-warning",
  danger: "before:bg-tone-danger",
  info: "before:bg-tone-info",
  neutral: "before:bg-tone-neutral",
} as const satisfies Record<Tone, string>;

/**
 * Label + big value + optional delta/sub-label (§4.3): "Current Temperature", "Prediction
 * Confidence", "Relative Humidity", … Values are passed in already formatted from API fields;
 * the card never computes them.
 */
export function MetricCard({
  label,
  value,
  unit,
  delta,
  subLabel,
  icon: Icon,
  tags,
  accent,
  loading = false,
  className,
}: MetricCardProps) {
  const DeltaIcon = delta ? DELTA_ICON[delta.direction ?? "flat"] : null;
  return (
    <section
      data-slot="metric-card"
      aria-busy={loading || undefined}
      aria-label={label}
      className={cn(
        "relative flex min-w-0 flex-col gap-3 overflow-hidden rounded-xl border bg-card p-5 text-card-foreground shadow-xs",
        accent && cn("before:absolute before:inset-y-0 before:left-0 before:w-1", ACCENT[accent]),
        className,
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="flex min-w-0 items-center gap-2">
          {Icon && (
            <span className="grid size-7 shrink-0 place-items-center rounded-md bg-muted text-muted-foreground">
              <Icon aria-hidden="true" className="size-4" />
            </span>
          )}
          <h3 className={cn(typography.metricLabel, "truncate")}>{label}</h3>
        </div>
        {tags && <div className="flex shrink-0 flex-wrap justify-end gap-1">{tags}</div>}
      </div>

      {loading ? (
        <div className="flex flex-col gap-2" aria-hidden="true">
          <Skeleton className="h-9 w-28" />
          <Skeleton className="h-4 w-40" />
        </div>
      ) : (
        <div className="flex min-w-0 flex-col gap-1.5">
          <div className="flex min-w-0 items-baseline gap-1.5">
            <span className={cn(typography.metricValue, "truncate")}>{value}</span>
            {unit && <span className="text-base font-medium text-muted-foreground">{unit}</span>}
          </div>
          {delta && DeltaIcon && (
            <p
              className={cn(
                "inline-flex items-center gap-1 text-xs font-medium",
                TONE_STYLE[delta.tone ?? "neutral"].text,
              )}
            >
              <DeltaIcon aria-hidden="true" className="size-3.5" />
              {delta.text}
            </p>
          )}
          {subLabel && <p className="text-xs text-muted-foreground">{subLabel}</p>}
        </div>
      )}
    </section>
  );
}
