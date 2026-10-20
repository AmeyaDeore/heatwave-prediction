/** Display rules for SHAP factors (Part 06 §3), shared by every factor visual. */
import type { FactorDirection } from "@/lib/api/types";
import { formatFixed } from "./labels";
import type { Tone } from "./tokens";

/**
 * Direction → colour. Raising heat risk is amber (the Heatwave tone); lowering it is blue
 * (cooling). Green is deliberately not used for "raises risk", although a mockup did: green
 * means "Normal / safe" everywhere else, and one colour must not mean two things (§4.1).
 */
export const DIRECTION_TONE: Record<FactorDirection, Tone> = {
  increases_risk: "warning",
  decreases_risk: "info",
  neutral: "neutral",
};

/** "+65.0%" / "-3.1%", straight from the API's signed share_pct (never re-derived). */
export function formatShare(sharePct: number): string {
  const text = formatFixed(sharePct, 1);
  return `${text.startsWith("-") ? text : `+${text}`}%`;
}
