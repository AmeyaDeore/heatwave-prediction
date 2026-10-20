import { RISK_ICON } from "@/design/icons";
import { riskLabel, type RiskClass } from "@/design/labels";
import { RISK_TONE, TONE_STYLE } from "@/design/tokens";
import { cn } from "@/lib/utils";

const SIZE = {
  sm: "h-5 gap-1 px-2 text-[0.6875rem] [&_svg]:size-3",
  md: "h-6 gap-1.5 px-2.5 text-xs [&_svg]:size-3.5",
  lg: "h-8 gap-2 px-3.5 text-sm [&_svg]:size-4",
} as const;

export interface RiskBadgeProps {
  riskClass: RiskClass;
  size?: keyof typeof SIZE;
  /** `subtle` (tinted, default) for tables and lists; `solid` for emphasis on dark/banner use. */
  variant?: "subtle" | "solid";
  /** Uppercase, as on the mockups' "SEVERE" labels. */
  uppercase?: boolean;
  className?: string;
}

/**
 * Risk class as a coloured pill (§4.3). Used by the dashboard table, the prediction banner and
 * the alerts list. The colour comes from RISK_TONE and the text from config/feature_labels.json.
 */
export function RiskBadge({
  riskClass,
  size = "md",
  variant = "subtle",
  uppercase = true,
  className,
}: RiskBadgeProps) {
  const tone = TONE_STYLE[RISK_TONE[riskClass]];
  const Icon = RISK_ICON[riskClass];
  return (
    <span
      data-slot="risk-badge"
      data-risk={riskClass}
      className={cn(
        "inline-flex w-fit shrink-0 items-center rounded-full border font-semibold whitespace-nowrap",
        uppercase && "tracking-wide uppercase",
        variant === "solid" ? cn(tone.solid, "border-transparent") : tone.subtle,
        SIZE[size],
        className,
      )}
    >
      <Icon aria-hidden="true" strokeWidth={2.25} />
      {riskLabel(riskClass)}
    </span>
  );
}
