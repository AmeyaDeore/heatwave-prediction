/**
 * The one QueryClient, with the retry convention (Part 10 §3):
 *   - queries retry transient failures (network, timeout, upstream 503, 5xx, 429) up to twice,
 *     with exponential backoff, honouring Retry-After; client errors (4xx) never retry
 *   - mutations never retry automatically: an alert is issued by a person, once
 */
import { QueryClient } from "@tanstack/react-query";
import { isApiError } from "@/lib/api/errors";

export const MAX_QUERY_RETRIES = 2;

export function shouldRetry(failureCount: number, error: unknown): boolean {
  if (failureCount >= MAX_QUERY_RETRIES) return false;
  return isApiError(error) ? error.isTransient : false;
}

export function retryDelay(attempt: number, error: unknown): number {
  if (isApiError(error) && error.retryAfter !== null) return error.retryAfter * 1_000;
  return Math.min(1_000 * 2 ** attempt, 8_000);
}

export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: shouldRetry,
        retryDelay,
        staleTime: 30_000,
        refetchOnWindowFocus: true,
        refetchOnReconnect: true,
      },
      mutations: { retry: false },
    },
  });
}
