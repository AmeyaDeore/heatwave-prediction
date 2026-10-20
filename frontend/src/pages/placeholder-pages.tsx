/**
 * Route placeholders for the four pages built in Parts 11–14. Each renders inside the shell with
 * its final title, so navigation, region switching and "last updated" can be exercised now.
 * Each part replaces its placeholder with the real page.
 */
import { Construction, MapPinned } from "lucide-react";
import { Link } from "react-router";
import { PageHeader } from "@/components/shared/panel";
import { EmptyState } from "@/components/shared/states";
import { Button } from "@/components/ui/button";
import { layout } from "@/design/tokens";
import { cn } from "@/lib/utils";
import { regionDisplayName, useRegion } from "@/state/region-context";

function RegionContext() {
  const { region, regionId } = useRegion();
  return (
    <span className="inline-flex items-center gap-1 text-sm font-medium text-foreground">
      <MapPinned aria-hidden="true" className="size-4 text-muted-foreground" />
      {regionDisplayName(region, regionId)}
    </span>
  );
}

function Placeholder({ title, subtitle, part }: { title: string; subtitle: string; part: string }) {
  return (
    <div className={cn(layout.page, layout.pageStack)}>
      <PageHeader title={title} subtitle={subtitle} context={<RegionContext />} />
      <div className="rounded-xl border border-dashed bg-card">
        <EmptyState
          icon={Construction}
          title={`Built in Part ${part}`}
          description="The navigation shell, region selection and shared components are ready for this page."
          action={
            <Button asChild variant="outline" size="sm">
              <Link to="/design-system">View the design system</Link>
            </Button>
          }
        />
      </div>
    </div>
  );
}

export const PredictionsPage = () => (
  <Placeholder
    title="Heatwave Prediction"
    subtitle="AI-powered short-term heatwave risk assessment"
    part="12"
  />
);
export const AlertsPage = () => (
  <Placeholder
    title="Heatwave Early Warning"
    subtitle="Alert creation and authority response management"
    part="13"
  />
);
export const AnalyticsPage = () => (
  <Placeholder title="Analytics" subtitle="Historical trends and model performance" part="14" />
);

export function NotFoundPage() {
  return (
    <div className={layout.page}>
      <EmptyState
        title="Page not found"
        description="This address doesn't match any page."
        action={
          <Button asChild size="sm">
            <Link to="/">Go to the dashboard</Link>
          </Button>
        }
      />
    </div>
  );
}
