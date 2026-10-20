import { BarChart3, BellRing, BrainCircuit, LayoutDashboard, type LucideIcon } from "lucide-react";

export interface NavItem {
  to: string;
  label: string;
  icon: LucideIcon;
  /** The plan part that builds the page. */
  part: string;
}

/** The four primary nav items, in mockup order (Part 10 §2.2), one per page in Parts 11–14. */
export const NAV_ITEMS: NavItem[] = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard, part: "11" },
  { to: "/predictions", label: "Predictions", icon: BrainCircuit, part: "12" },
  { to: "/alerts", label: "Alerts", icon: BellRing, part: "13" },
  { to: "/analytics", label: "Analytics", icon: BarChart3, part: "14" },
];

/**
 * Per-route shell options, set as the route's `handle` in src/app/router.tsx.
 * `showLastUpdated`: the data-heavy screens show the "last updated" indicator (§2.4).
 */
export interface RouteHandle {
  title: string;
  showLastUpdated?: boolean;
}

export const PRODUCT_NAME = "Climate Intelligence";

/** Where /login sends a signed-in official: same-app paths only, never an absolute or
 *  protocol-relative URL (no open redirect). */
export function safeNext(raw: string | null): string {
  if (!raw || !raw.startsWith("/") || raw.startsWith("//") || raw.startsWith("/login")) return "/";
  return raw;
}
