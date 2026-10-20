import { Clock, FlaskConical, Radio, Sparkles, Zap, type LucideIcon } from "lucide-react";
import { TONE_STYLE, typography, type Tone } from "@/design/tokens";
import { cn } from "@/lib/utils";

/**
 * Presets for the small inline labels on nearly every card (§4.3): where the data came from,
 * and whether the content is AI-derived. New kinds are added here, not invented per page.
 */
export const DATA_SOURCE_PRESETS = {
  demo: {
    label: "Demo data",
    tone: "neutral",
    icon: FlaskConical,
    title: "Sample or synthetic data, not a live feed.",
  },
  live: { label: "Live", tone: "success", icon: Radio, title: "Refreshes automatically." },
  stale: {
    label: "Stale data",
    tone: "warning",
    icon: Clock,
    title: "The weather data is older than expected. It is still shown, but treat it with care.",
  },
  ai: {
    label: "AI explained",
    tone: "info",
    icon: Sparkles,
    title: "Factors computed by the model's SHAP explainer for this exact prediction.",
  },
  act: {
    label: "Act now",
    tone: "danger",
    icon: Zap,
    title: "Recommended actions for the current risk level.",
  },
} satisfies Record<string, { label: string; tone: Tone; icon: LucideIcon; title: string }>;

export type DataSourceKind = keyof typeof DATA_SOURCE_PRESETS;

export interface DataSourceTagProps {
  kind?: DataSourceKind;
  /** Override or supply the preset's parts, e.g. `label="Model xgboost-…"` with tone neutral. */
  label?: string;
  tone?: Tone;
  icon?: LucideIcon | null;
  /** Hover text explaining the tag. */
  title?: string;
  className?: string;
}

export function DataSourceTag({ kind, label, tone, icon, title, className }: DataSourceTagProps) {
  const preset = kind ? DATA_SOURCE_PRESETS[kind] : undefined;
  const resolvedTone: Tone = tone ?? preset?.tone ?? "neutral";
  const Icon = icon === null ? null : (icon ?? preset?.icon ?? null);
  const text = label ?? preset?.label ?? "";
  return (
    <span
      data-slot="data-source-tag"
      data-kind={kind}
      title={title ?? preset?.title}
      className={cn(
        "inline-flex h-5 w-fit shrink-0 items-center gap-1 rounded-sm border px-1.5 whitespace-nowrap [&_svg]:size-3",
        typography.meta,
        TONE_STYLE[resolvedTone].subtle,
        className,
      )}
    >
      {Icon && <Icon aria-hidden="true" strokeWidth={2.5} />}
      {text}
    </span>
  );
}
