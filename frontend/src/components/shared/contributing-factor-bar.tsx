import { ArrowDown, ArrowUp, CircleHelp, Minus } from "lucide-react";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { TONE_STYLE, typography } from "@/design/tokens";
import type { FactorDirection, FactorOut } from "@/lib/api/types";
import { DIRECTION_TONE, formatShare } from "@/design/factors";
import { cn } from "@/lib/utils";

const DIRECTION_TEXT: Record<FactorDirection, string> = {
  increases_risk: "raises heat risk",
  decreases_risk: "lowers heat risk",
  neutral: "no effect",
};

const DIRECTION_ICON = { increases_risk: ArrowUp, decreases_risk: ArrowDown, neutral: Minus };

export interface ContributingFactorBarProps {
  factor: FactorOut;
  /**
   * The |share_pct| that fills one half of the track. 100 (default) keeps bars comparable
   * across predictions; pass the largest |share_pct| to use the full width in a condensed view.
   */
  scaleMax?: number;
  /** Hide the value column in tight layouts (dashboard condensed panel). */
  showValue?: boolean;
  className?: string;
}

/**
 * One SHAP factor (§4.3): name, the value the model used, and a diverging bar from a centre
 * axis. Length = |share_pct|, right = raises risk, left = lowers risk (Part 06 §3). Consumes
 * FactorOut from the API unchanged.
 */
export function ContributingFactorBar({
  factor,
  scaleMax = 100,
  showValue = true,
  className,
}: ContributingFactorBarProps) {
  const tone = TONE_STYLE[DIRECTION_TONE[factor.direction]];
  const Icon = DIRECTION_ICON[factor.direction];
  const width = Math.min(100, (Math.abs(factor.share_pct) / Math.max(scaleMax, 0.1)) * 100);
  const share = formatShare(factor.share_pct);

  return (
    <div
      data-slot="contributing-factor"
      data-direction={factor.direction}
      className={cn(
        "grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-3 gap-y-1.5",
        className,
      )}
    >
      <div className="flex min-w-0 items-center gap-1.5">
        <span className={cn(typography.body, "truncate font-medium")}>{factor.label}</span>
        {factor.imputed && (
          <Tooltip>
            <TooltipTrigger
              type="button"
              className="inline-flex items-center gap-0.5 rounded-sm text-meta font-semibold tracking-wide text-muted-foreground uppercase outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50"
            >
              <CircleHelp aria-hidden="true" className="size-3" />
              Estimated
            </TooltipTrigger>
            <TooltipContent>
              This reading was missing, so the model used the typical value for this month.
            </TooltipContent>
          </Tooltip>
        )}
      </div>
      <div className="tabular flex items-center gap-3 text-sm">
        {showValue && <span className="text-muted-foreground">{factor.display_value}</span>}
        <span
          className={cn(
            "inline-flex w-[4.75rem] items-center justify-end gap-0.5 font-semibold",
            tone.text,
          )}
        >
          <Icon aria-hidden="true" className="size-3.5" />
          {share}
          <span className="sr-only">, {DIRECTION_TEXT[factor.direction]}</span>
        </span>
      </div>

      {/* Diverging track: left half = lowers risk, right half = raises risk. */}
      <div className="col-span-2 grid h-2 grid-cols-2" aria-hidden="true">
        <div className="flex justify-end overflow-hidden rounded-l-full bg-muted">
          {factor.share_pct < 0 && (
            <div className={cn("h-full rounded-l-full", tone.bar)} style={{ width: `${width}%` }} />
          )}
        </div>
        <div className="flex overflow-hidden rounded-r-full border-l-2 border-background bg-muted">
          {factor.share_pct > 0 && (
            <div className={cn("h-full rounded-r-full", tone.bar)} style={{ width: `${width}%` }} />
          )}
        </div>
      </div>
    </div>
  );
}

export interface FactorListProps {
  factors: FactorOut[];
  /** Show only the top N by rank (the dashboard shows 2–3; the Prediction page shows all). */
  limit?: number;
  /** Scale bars to the largest shown share instead of 100 %. */
  fitScale?: boolean;
  showValue?: boolean;
  showLegend?: boolean;
  className?: string;
}

/** Ranked factor bars with an optional legend; the standard SHAP display for Parts 11 and 12. */
export function FactorList({
  factors,
  limit,
  fitScale = false,
  showValue = true,
  showLegend = true,
  className,
}: FactorListProps) {
  const shown = [...factors].sort((a, b) => a.rank - b.rank).slice(0, limit ?? factors.length);
  const scaleMax = fitScale ? Math.max(...shown.map((f) => Math.abs(f.share_pct)), 1) : 100;
  return (
    <div className={cn("flex flex-col gap-4", className)}>
      <ol className="flex flex-col gap-4" aria-label="Contributing factors, most influential first">
        {shown.map((factor) => (
          <li key={factor.feature}>
            <ContributingFactorBar factor={factor} scaleMax={scaleMax} showValue={showValue} />
          </li>
        ))}
      </ol>
      {showLegend && (
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
          <span className="inline-flex items-center gap-1.5">
            <span
              aria-hidden="true"
              className={cn("size-2.5 rounded-full", TONE_STYLE.warning.dot)}
            />
            Raises heat risk
          </span>
          <span className="inline-flex items-center gap-1.5">
            <span aria-hidden="true" className={cn("size-2.5 rounded-full", TONE_STYLE.info.dot)} />
            Lowers heat risk
          </span>
          <span>Share of the model's decision</span>
        </div>
      )}
    </div>
  );
}
