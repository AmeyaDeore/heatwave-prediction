/**
 * Refresh policy (Part 10 §3, "polling vs. manual refresh"), decided once per kind of data so
 * pages don't choose ad hoc. Hooks in ./hooks.ts apply these; a page never sets its own
 * refetchInterval.
 *
 * | Data                         | Policy                                   | Why                                         |
 * |------------------------------|------------------------------------------|---------------------------------------------|
 * | Reference (regions, channels)| Load once per session                    | Comes from config files; changes on deploy   |
 * | Live (dashboard weather,     | Poll every VITE_DASHBOARD_POLL_INTERVAL_MS| The command center must feel live. Paused    |
 * |  latest prediction, ready)   | (60 s), refetch on focus/reconnect       | while the tab is hidden                      |
 * | Prediction page              | Manual: latest stored prediction, refetch| It is a read-model page; "Recompute" is an   |
 * |                              | on focus; explicit Recompute = POST      | explicit, rate-limited action (Part 12 §3)   |
 * | Alerts list                  | Manual + refetch on focus                | Changes only when an official acts          |
 * | Alert detail                 | Poll every 3 s while delivery is PENDING,| Part 09: dispatch is async and the UI polls  |
 * |                              | then stop                                | while delivery_summary.pending > 0          |
 * | Analytics                    | Manual only, no focus refetch            | Historical; moves at most daily             |
 */
import { env } from "@/lib/env";

const SECOND = 1_000;
const MINUTE = 60 * SECOND;

export const REFRESH_POLICY = {
  reference: { staleTime: Infinity, gcTime: Infinity, refetchOnWindowFocus: false },
  live: {
    staleTime: 30 * SECOND,
    refetchInterval: env.dashboardPollIntervalMs,
    refetchIntervalInBackground: false,
    refetchOnWindowFocus: true,
  },
  onDemand: { staleTime: 5 * MINUTE, refetchOnWindowFocus: true },
  list: { staleTime: 30 * SECOND, refetchOnWindowFocus: true },
  historical: { staleTime: 10 * MINUTE, refetchOnWindowFocus: false },
} as const;

/** How often an issued alert's delivery status is polled while any channel is PENDING. */
export const DELIVERY_POLL_INTERVAL_MS = 3 * SECOND;
