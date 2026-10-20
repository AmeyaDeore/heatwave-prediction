import { createBrowserRouter, type RouteObject } from "react-router";
import { AppShell } from "@/components/layout/app-shell";
import { RequireSession } from "@/components/layout/require-session";
import { RouteErrorBoundary, RouteLoading } from "@/components/layout/route-error";
import type { RouteHandle } from "./navigation";

const handle = (h: RouteHandle) => h;

/**
 * Every page is a child of the shell (§2: one shared layout, never a per-page header) and is
 * loaded on demand, so each page ships as its own chunk. Parts 11–14 replace a placeholder by
 * pointing its `lazy` import at the real page module.
 */
export const routes: RouteObject[] = [
  {
    // Outside the shell and the guard: the one page a signed-out visitor can see (Part 15 R2).
    path: "login",
    errorElement: <RouteErrorBoundary />,
    hydrateFallbackElement: <RouteLoading />,
    lazy: async () => ({ Component: (await import("@/pages/login-page")).LoginPage }),
    handle: handle({ title: "Sign in" }),
  },
  {
    element: (
      <RequireSession>
        <AppShell />
      </RequireSession>
    ),
    errorElement: <RouteErrorBoundary />,
    // Shown while the first page chunk loads (lazy routes); later navigations keep the shell.
    hydrateFallbackElement: <RouteLoading />,
    children: [
      {
        index: true,
        lazy: async () => ({
          Component: (await import("@/pages/dashboard-page")).DashboardPage,
        }),
        handle: handle({ title: "Dashboard", showLastUpdated: true }),
      },
      {
        path: "predictions",
        lazy: async () => ({
          Component: (await import("@/pages/prediction-page")).PredictionPage,
        }),
        handle: handle({ title: "Predictions", showLastUpdated: true }),
      },
      {
        path: "alerts",
        lazy: async () => ({ Component: (await import("@/pages/alerts-page")).AlertsPage }),
        handle: handle({ title: "Alerts", showLastUpdated: true }),
      },
      {
        path: "analytics",
        lazy: async () => ({
          Component: (await import("@/pages/analytics-page")).AnalyticsPage,
        }),
        handle: handle({ title: "Analytics", showLastUpdated: true }),
      },
      {
        path: "design-system",
        lazy: async () => ({
          Component: (await import("@/pages/design-system-page")).DesignSystemPage,
        }),
        handle: handle({ title: "Design system" }),
      },
      {
        path: "*",
        lazy: async () => ({ Component: (await import("@/pages/placeholder-pages")).NotFoundPage }),
        handle: handle({ title: "Not found" }),
      },
    ],
  },
];

export function createRouter() {
  return createBrowserRouter(routes);
}
