/**
 * Selected region (Part 10 §2.3, §3): one global, persistent selection, changed from the nav
 * shell and read by every page's queries.
 *
 * Precedence on load: `?region=` in the URL (so a drill-through or shared link opens the right
 * place) → the last choice (localStorage) → VITE_DEFAULT_REGION. Once the region list arrives,
 * an id that no longer exists falls back to the default, then to the first region.
 *
 * Queries start with the stored id immediately instead of waiting for the region list.
 */
import { useQuery } from "@tanstack/react-query";
import { useCallback, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { api } from "@/lib/api/endpoints";
import { env } from "@/lib/env";
import { queryKeys } from "@/lib/query/keys";
import { REFRESH_POLICY } from "@/lib/query/policy";
import { readStored, STORAGE_KEYS, writeStored } from "@/lib/storage";
import { REGION_PARAM, RegionContext, type RegionContextValue } from "./region-context";
import { useSession } from "./session-context";

const REGION_ID = /^[a-z][a-z0-9_]{1,40}$/; // The backend's own rule (docs/api §1).

function parseRegionId(raw: unknown): string | null {
  return typeof raw === "string" && REGION_ID.test(raw) ? raw : null;
}

function initialRegionId(): string {
  try {
    const fromUrl = parseRegionId(new URLSearchParams(window.location.search).get(REGION_PARAM));
    if (fromUrl) return fromUrl;
  } catch {
    // No usable location (tests, unusual embeds): fall through.
  }
  return readStored("local", STORAGE_KEYS.region, parseRegionId) ?? env.defaultRegionId;
}

export function RegionProvider({ children }: { children: ReactNode }) {
  const { isAuthenticated } = useSession();
  const [selectedId, setSelectedId] = useState<string>(initialRegionId);
  const {
    data,
    status: regionsStatus,
    error: regionsError,
    refetch,
  } = useQuery({
    queryKey: queryKeys.regions(),
    queryFn: ({ signal }) => api.regions({ signal }),
    ...REFRESH_POLICY.reference,
    // Revision 2: the region list needs a session; it loads once the official signs in.
    enabled: isAuthenticated,
  });
  const regions = useMemo(() => data ?? [], [data]);

  const setRegionId = useCallback((next: string) => {
    if (!parseRegionId(next)) return;
    setSelectedId(next);
    writeStored("local", STORAGE_KEYS.region, next);
  }, []);

  // A stale or mistyped id is repaired by derivation once the real list is known: no effect,
  // no extra render, and the stored choice is overwritten only when the user picks again.
  const regionId = useMemo(() => {
    if (regions.length === 0 || regions.some((r) => r.id === selectedId)) return selectedId;
    return (regions.find((r) => r.id === env.defaultRegionId) ?? regions[0])?.id ?? selectedId;
  }, [regions, selectedId]);

  const value = useMemo<RegionContextValue>(
    () => ({
      regionId,
      region: regions.find((r) => r.id === regionId) ?? null,
      regions,
      regionsStatus,
      regionsError,
      refetchRegions: () => void refetch(),
      setRegionId,
    }),
    [regionId, regions, regionsStatus, regionsError, refetch, setRegionId],
  );

  return <RegionContext.Provider value={value}>{children}</RegionContext.Provider>;
}
