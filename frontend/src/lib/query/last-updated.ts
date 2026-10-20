/**
 * "Last updated" (Part 10 §2.4): the time of the most recent successful fetch among the queries
 * the current screen is showing. Derived from the query cache, so pages don't report it.
 */
import { useIsFetching, useQueryClient } from "@tanstack/react-query";
import { useCallback, useSyncExternalStore } from "react";
import { queryKeys } from "./keys";

/** Reference data (regions, channels) loads once per session; it says nothing about freshness. */
const EXCLUDED = new Set<string>(["regions", "alert-channels", "readiness"]);

export function useLastUpdated() {
  const client = useQueryClient();
  const cache = client.getQueryCache();

  const subscribe = useCallback((onChange: () => void) => cache.subscribe(onChange), [cache]);
  const getSnapshot = useCallback(() => {
    let latest = 0;
    for (const query of cache.findAll({ queryKey: queryKeys.all, type: "active" })) {
      const kind = String(query.queryKey[1]);
      if (EXCLUDED.has(kind) || query.state.status !== "success") continue;
      latest = Math.max(latest, query.state.dataUpdatedAt);
    }
    return latest;
  }, [cache]);

  const updatedAt = useSyncExternalStore(subscribe, getSnapshot, getSnapshot);
  const fetching = useIsFetching({ queryKey: queryKeys.all, type: "active" }) > 0;
  const refresh = useCallback(
    () => client.refetchQueries({ queryKey: queryKeys.all, type: "active" }),
    [client],
  );

  return { updatedAt: updatedAt || null, fetching, refresh };
}
