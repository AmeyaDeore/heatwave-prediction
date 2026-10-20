/**
 * The navigation shell (Part 10 §2): one layout every page renders inside. Top bar, in order:
 * branding, the four nav items, the selected region, and "last updated" on data-heavy screens.
 * Pages never render their own header chrome.
 */
import { CloudSun, TriangleAlert } from "lucide-react";
import { useEffect } from "react";
import {
  Link,
  NavLink,
  Outlet,
  ScrollRestoration,
  useMatches,
  useSearchParams,
} from "react-router";
import { Toaster } from "@/components/ui/sonner";
import { NAV_ITEMS, PRODUCT_NAME, type RouteHandle } from "@/app/navigation";
import { useReadiness } from "@/lib/query/hooks";
import { cn } from "@/lib/utils";
import { REGION_PARAM, useRegion } from "@/state/region-context";
import { LastUpdated } from "./last-updated";
import { RegionSelector } from "./region-selector";
import { SignInDialog } from "./sign-in-dialog";
import { UserMenu } from "./user-menu";

function useRouteHandle(): RouteHandle | undefined {
  const matches = useMatches();
  return matches.map((m) => m.handle as RouteHandle | undefined).findLast(Boolean);
}

/** A `?region=` link (drill-through, shared URL) selects that region, then leaves the URL clean. */
function useRegionFromUrl() {
  const [params, setParams] = useSearchParams();
  const { setRegionId } = useRegion();
  const fromUrl = params.get(REGION_PARAM);
  useEffect(() => {
    if (!fromUrl) return;
    setRegionId(fromUrl);
    const next = new URLSearchParams(params);
    next.delete(REGION_PARAM);
    setParams(next, { replace: true });
  }, [fromUrl, params, setParams, setRegionId]);
}

function Brand() {
  return (
    <Link
      to="/"
      className="flex shrink-0 items-center gap-2.5 rounded-md outline-none focus-visible:ring-[3px] focus-visible:ring-nav-muted/50"
    >
      <span className="grid size-8 place-items-center rounded-lg bg-gradient-to-br from-tone-warning to-tone-danger text-tone-danger-fg shadow-sm">
        <CloudSun aria-hidden="true" className="size-4.5" strokeWidth={2.25} />
      </span>
      <span className="flex flex-col leading-none">
        <span className="text-sm font-semibold tracking-tight text-nav-foreground">
          {PRODUCT_NAME}
        </span>
        <span className="hidden text-[0.6875rem] text-nav-muted sm:block">
          Heatwave early warning
        </span>
      </span>
    </Link>
  );
}

function PrimaryNav({ className }: { className?: string }) {
  return (
    <nav aria-label="Primary" className={className}>
      <ul className="flex items-center gap-1">
        {NAV_ITEMS.map(({ to, label, icon: Icon }) => (
          <li key={to}>
            <NavLink
              to={to}
              end={to === "/"}
              className={({ isActive }) =>
                cn(
                  "flex h-9 items-center gap-2 rounded-md px-3 text-sm font-medium whitespace-nowrap text-nav-muted transition-colors outline-none hover:bg-nav-accent hover:text-nav-foreground focus-visible:ring-[3px] focus-visible:ring-nav-muted/50",
                  isActive && "bg-nav-accent text-nav-foreground",
                )
              }
            >
              <Icon aria-hidden="true" className="size-4" />
              {label}
            </NavLink>
          </li>
        ))}
      </ul>
    </nav>
  );
}

/** Weather older than the backend's freshness limit is still served; the shell says so. */
function DataHealth() {
  const { data } = useReadiness();
  if (!data || data.weather_data === "ok") return null;
  const unavailable = data.weather_data === "unavailable";
  return (
    <span
      role="status"
      title={
        unavailable
          ? "The backend cannot read weather data. Predictions may fail."
          : "The latest weather data is older than expected. Figures are still shown."
      }
      className="hidden h-7 items-center gap-1.5 rounded-full border border-tone-warning-border bg-tone-warning-subtle px-2.5 text-xs font-semibold text-tone-warning-subtle-fg md:inline-flex"
    >
      <TriangleAlert aria-hidden="true" className="size-3.5" />
      {unavailable ? "Weather data unavailable" : "Weather data stale"}
    </span>
  );
}

export function AppShell() {
  const handle = useRouteHandle();
  useRegionFromUrl();

  useEffect(() => {
    document.title = handle?.title ? `${handle.title} · ${PRODUCT_NAME}` : PRODUCT_NAME;
  }, [handle?.title]);

  return (
    <div className="flex min-h-svh flex-col">
      <a
        href="#main"
        className="sr-only z-50 rounded-md bg-primary px-3 py-2 text-sm text-primary-foreground focus:not-sr-only focus:fixed focus:top-2 focus:left-2"
      >
        Skip to content
      </a>
      <header className="sticky top-0 z-40 bg-nav text-nav-foreground shadow-sm">
        <div className="mx-auto flex h-14 w-full max-w-screen-2xl items-center gap-4 px-4 sm:px-6 lg:px-8">
          <Brand />
          <PrimaryNav className="hidden lg:block" />
          <div className="ml-auto flex min-w-0 items-center gap-2">
            <DataHealth />
            <RegionSelector className="max-w-[11rem] sm:max-w-none" />
            {handle?.showLastUpdated && <LastUpdated className="hidden md:flex" />}
            <UserMenu />
          </div>
        </div>
        {/* Below lg the nav items move to a scrollable second row, so all four stay one tap away. */}
        <div className="border-t border-nav-accent lg:hidden">
          <div className="mx-auto flex w-full max-w-screen-2xl items-center gap-2 overflow-x-auto px-4 py-1.5 sm:px-6">
            <PrimaryNav />
            {handle?.showLastUpdated && <LastUpdated className="ml-auto md:hidden" />}
          </div>
        </div>
      </header>

      <main id="main" tabIndex={-1} className="flex-1 outline-none">
        <Outlet />
      </main>

      <footer className="border-t bg-card">
        <div className="mx-auto flex w-full max-w-screen-2xl flex-wrap items-center justify-between gap-2 px-4 py-3 text-xs text-muted-foreground sm:px-6 lg:px-8">
          <span>
            {PRODUCT_NAME} · Short-term heatwave risk (next 1–3 days) for disaster management
            officials
          </span>
          <ModelVersion />
        </div>
        {/* The brand accent bar seen at the bottom of every screen (§4.1). */}
        <div aria-hidden="true" className="h-1 bg-brand-accent" />
      </footer>

      <SignInDialog />
      <Toaster position="bottom-right" />
      <ScrollRestoration />
    </div>
  );
}

function ModelVersion() {
  const { data } = useReadiness();
  if (!data) return null;
  return (
    <span className="font-mono" title={`Explainer ${data.explainer_id}`}>
      Model {data.model_version}
    </span>
  );
}
