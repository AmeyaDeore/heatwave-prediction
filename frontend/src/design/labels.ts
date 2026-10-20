/**
 * User-facing names for risk classes and model features.
 *
 * Read from config/feature_labels.json (Part 06 §5), the same table the ML code and the backend
 * use. Never copy these strings into components: import from here.
 */
import table from "@config/feature_labels.json";

/** The exact risk vocabulary used in the database, the API and the UI (CLAUDE.md). */
export const RISK_CLASSES = ["NORMAL", "HEATWAVE", "SEVERE_HEATWAVE"] as const;
export type RiskClass = (typeof RISK_CLASSES)[number];

export type FeatureKey = keyof typeof table.features;
export type FeatureDisplay = (typeof table.features)[FeatureKey];

export const RISK_LABELS: Record<RiskClass, string> = table.risk_classes;
export const FEATURE_DISPLAY: Record<FeatureKey, FeatureDisplay> = table.features;

export function isRiskClass(value: unknown): value is RiskClass {
  return typeof value === "string" && (RISK_CLASSES as readonly string[]).includes(value);
}

export function riskLabel(riskClass: RiskClass): string {
  return RISK_LABELS[riskClass];
}

export function featureLabel(feature: string): string {
  return FEATURE_DISPLAY[feature as FeatureKey]?.label ?? feature;
}

/**
 * Format a raw input value with the shared unit and precision ("42.6 °C", "+3.0 °C", "79%").
 * Mirrors heatwave_ml.explainability.summary.format_value exactly, so a metric card and the
 * factor's `display_value` for the same input never disagree. Explanation factors already
 * carry `display_value`: use that, not this.
 */
export function formatFeatureValue(feature: string, value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  const display = FEATURE_DISPLAY[feature as FeatureKey];
  if (!display) return String(value);
  const fixed = formatFixed(value, display.decimals);
  const number = display.signed && !fixed.startsWith("-") ? `+${fixed}` : fixed;
  return display.unit === "%" ? `${number}%` : `${number} ${display.unit}`;
}

/** A whole percentage that never claims certainty. Mirrors summary.format_probability. */
export function formatProbability(p: number): string {
  if (p >= 0.995) return ">99%";
  if (p < 0.005) return "<1%";
  return `${formatFixed(p * 100, 0)}%`;
}

/**
 * Python's f"{x:.Nf}": round the exact binary value, ties to even. toFixed() rounds ties away
 * from zero, so 31.25 would show as "31.3" here and "31.2" in the API's summary sentence.
 * toFixed(100) yields the double's exact decimal expansion, which makes ties detectable.
 */
export function formatFixed(value: number, decimals: number): string {
  const exact = Math.abs(value).toFixed(100);
  const point = exact.indexOf(".");
  const rest = exact.slice(point + 1 + decimals);
  const isTie = /^50*$/.test(rest);
  let out = Math.abs(value).toFixed(decimals);
  if (isTie) {
    const kept = exact.slice(0, point + 1 + decimals).replace(/\.$/, "");
    const lastDigit = Number(kept.at(-1));
    out = lastDigit % 2 === 0 ? kept : out;
  }
  const negative = value < 0 || Object.is(value, -0);
  return negative ? `-${out}` : out;
}
