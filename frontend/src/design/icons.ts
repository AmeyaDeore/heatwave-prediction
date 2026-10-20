/**
 * Icon semantics, shared like the colour tokens: one icon per risk class and per recommended
 * action kind, so the same thing always looks the same.
 */
import {
  Building2,
  CircleCheck,
  ClipboardList,
  Droplets,
  Eye,
  Flame,
  HardHat,
  Hospital,
  Megaphone,
  MonitorSpeaker,
  Siren,
  Snowflake,
  ThermometerSun,
  type LucideIcon,
} from "lucide-react";
import type { RiskClass } from "./labels";

/** A distinct shape per class, so a risk badge reads correctly without colour (§5). */
export const RISK_ICON: Record<RiskClass, LucideIcon> = {
  NORMAL: CircleCheck,
  HEATWAVE: ThermometerSun,
  SEVERE_HEATWAVE: Flame,
};

/**
 * Icon per recommended action, matched on keywords from config/recommended_actions.yaml
 * (RA-v1). Unknown wording falls back to a checklist icon, so a new action never breaks the UI.
 */
export const ACTION_ICONS = {
  health: Hospital,
  cooling: Snowflake,
  workers: HardHat,
  emergency: Siren,
  boards: MonitorSpeaker,
  humidity: Droplets,
  advisory: Megaphone,
  monitoring: Eye,
  ward: Building2,
  other: ClipboardList,
} satisfies Record<string, LucideIcon>;

export type ActionIconKey = keyof typeof ACTION_ICONS;

const ACTION_ICON_RULES: [RegExp, ActionIconKey][] = [
  [/hospital|health/i, "health"],
  [/cooling/i, "cooling"],
  [/outdoor work|worker/i, "workers"],
  [/emergency|field response|standby/i, "emergency"],
  [/display board/i, "boards"],
  [/humid|hydrat/i, "humidity"],
  [/advisory|warning|alert/i, "advisory"],
  [/monitor/i, "monitoring"],
  [/ward|municipal/i, "ward"],
];

export function actionIconKey(text: string): ActionIconKey {
  return ACTION_ICON_RULES.find(([pattern]) => pattern.test(text))?.[1] ?? "other";
}
