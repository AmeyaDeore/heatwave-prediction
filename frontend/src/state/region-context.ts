import { createContext, useContext } from "react";
import type { RegionOut } from "@/lib/api/types";

/** The URL parameter a drill-through or shared link uses to open a region. */
export const REGION_PARAM = "region";

export interface RegionContextValue {
  regionId: string;
  /** The full record, once the region list has loaded. */
  region: RegionOut | null;
  regions: RegionOut[];
  regionsStatus: "pending" | "error" | "success";
  regionsError: unknown;
  refetchRegions: () => void;
  setRegionId: (regionId: string) => void;
}

export const RegionContext = createContext<RegionContextValue | null>(null);

export function useRegion(): RegionContextValue {
  const context = useContext(RegionContext);
  if (!context) throw new Error("useRegion must be used inside <RegionProvider>.");
  return context;
}

/** A link that opens `path` for a specific region, e.g. the dashboard's drill-through. */
export function withRegion(path: string, regionId: string): string {
  const [base, search = ""] = path.split("?");
  const params = new URLSearchParams(search);
  params.set(REGION_PARAM, regionId);
  return `${base}?${params.toString()}`;
}

/** "Mumbai, Maharashtra" — the nav shell's location label (§2.3). */
export function regionDisplayName(region: RegionOut | null, fallbackId: string): string {
  return region ? `${region.name}, ${region.state}` : fallbackId;
}
