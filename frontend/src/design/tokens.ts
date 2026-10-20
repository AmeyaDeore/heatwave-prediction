/**
 * Semantic design tokens (Part 10 §4): which tone each risk class and operational status uses,
 * and the type-scale roles. Colours themselves live in src/styles/globals.css.
 *
 * Every page uses these maps through the shared components. A page that needs a risk colour
 * outside a component (a chart series, a banner border) uses RISK_STYLE / riskCssVar(), never a
 * Tailwind colour literal such as `bg-red-600`.
 */
import type { RiskClass } from "./labels";

export type Tone = "success" | "warning" | "danger" | "info" | "neutral";

/** Tailwind class recipes per tone. Literal strings so Tailwind's scanner generates them. */
export const TONE_STYLE: Record<
  Tone,
  { solid: string; subtle: string; text: string; border: string; bar: string; dot: string }
> = {
  success: {
    solid: "bg-tone-success text-tone-success-fg",
    subtle: "bg-tone-success-subtle text-tone-success-subtle-fg border-tone-success-border",
    text: "text-tone-success-subtle-fg",
    border: "border-tone-success-border",
    bar: "bg-tone-success",
    dot: "bg-tone-success",
  },
  warning: {
    solid: "bg-tone-warning text-tone-warning-fg",
    subtle: "bg-tone-warning-subtle text-tone-warning-subtle-fg border-tone-warning-border",
    text: "text-tone-warning-subtle-fg",
    border: "border-tone-warning-border",
    bar: "bg-tone-warning",
    dot: "bg-tone-warning",
  },
  danger: {
    solid: "bg-tone-danger text-tone-danger-fg",
    subtle: "bg-tone-danger-subtle text-tone-danger-subtle-fg border-tone-danger-border",
    text: "text-tone-danger-subtle-fg",
    border: "border-tone-danger-border",
    bar: "bg-tone-danger",
    dot: "bg-tone-danger",
  },
  info: {
    solid: "bg-tone-info text-tone-info-fg",
    subtle: "bg-tone-info-subtle text-tone-info-subtle-fg border-tone-info-border",
    text: "text-tone-info-subtle-fg",
    border: "border-tone-info-border",
    bar: "bg-tone-info",
    dot: "bg-tone-info",
  },
  neutral: {
    solid: "bg-tone-neutral text-tone-neutral-fg",
    subtle: "bg-tone-neutral-subtle text-tone-neutral-subtle-fg border-tone-neutral-border",
    text: "text-tone-neutral-subtle-fg",
    border: "border-tone-neutral-border",
    bar: "bg-tone-neutral",
    dot: "bg-tone-neutral",
  },
};

/**
 * THE risk-class → colour mapping (§4.1). Green = Normal, amber = Heatwave, red = Severe.
 * The colour always travels with the class's label from config/feature_labels.json and a
 * distinct icon (§5: colour is never the only signal). The mockups' "HIGH" wording is not used:
 * the vocabulary is fixed at Normal / Heatwave / Severe Heatwave (CLAUDE.md).
 */
export const RISK_TONE: Record<RiskClass, Tone> = {
  NORMAL: "success",
  HEATWAVE: "warning",
  SEVERE_HEATWAVE: "danger",
};

/** CSS custom property for a risk colour, for inline styles and chart libraries (Part 14). */
const RISK_VAR_SUFFIX: Record<RiskClass, string> = {
  NORMAL: "normal",
  HEATWAVE: "heatwave",
  SEVERE_HEATWAVE: "severe",
};
export function riskCssVar(
  riskClass: RiskClass,
  variant: "" | "fg" | "subtle" | "subtle-fg" | "border" = "",
) {
  const suffix = variant ? `-${variant}` : "";
  return `var(--risk-${RISK_VAR_SUFFIX[riskClass]}${suffix})`;
}

/**
 * Operational statuses (§4.3 Status pill), extended from the risk semantics:
 * green = done/good to go, amber = in progress, red = failed or a live warning, neutral = not
 * yet acted on. Alert statuses and channel delivery statuses share one map because the API
 * shares the READY word between them, and it must look the same in both places.
 */
export const OPERATIONAL_STATUSES = [
  "DRAFT",
  "READY",
  "PENDING",
  "NOTIFIED",
  "ISSUED",
  "FAILED",
] as const;
export type OperationalStatus = (typeof OPERATIONAL_STATUSES)[number];

export const STATUS_TONE: Record<OperationalStatus, Tone> = {
  DRAFT: "neutral",
  READY: "success",
  PENDING: "warning",
  NOTIFIED: "success",
  ISSUED: "info",
  FAILED: "danger",
};

/** Type scale roles (§4.2). Components and pages use these, not ad-hoc text sizes. */
export const typography = {
  pageTitle: "text-display font-semibold tracking-tight text-foreground",
  pageSubtitle: "text-sm text-muted-foreground",
  sectionTitle: "text-base font-semibold tracking-tight text-foreground",
  cardTitle: "text-sm font-semibold text-foreground",
  body: "text-sm leading-6 text-foreground",
  secondary: "text-sm text-muted-foreground",
  metricValue: "text-metric font-semibold tracking-tight tabular text-foreground",
  metricLabel: "text-xs font-medium text-muted-foreground",
  meta: "text-meta font-semibold uppercase tracking-[0.08em]",
} as const;

/**
 * Spacing (§4.2): Tailwind's 4 px unit. Cards use 20 px padding and 16 px internal gaps; page
 * grids use 16 px (mobile) / 24 px (desktop) gaps. Pages compose these instead of choosing.
 */
export const layout = {
  page: "mx-auto w-full max-w-screen-2xl px-4 py-6 sm:px-6 lg:px-8 lg:py-8",
  pageStack: "flex flex-col gap-6",
  grid: "grid gap-4 lg:gap-6",
  cardPadding: "p-5",
  cardGap: "gap-4",
} as const;
