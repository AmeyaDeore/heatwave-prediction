import { MapPin } from "lucide-react";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { regionDisplayName, useRegion } from "@/state/region-context";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";

/**
 * The global region selector (§2.3). Shows "Mumbai, Maharashtra"; changing it re-scopes every
 * page's queries, because their keys include the region id.
 */
export function RegionSelector({ className }: { className?: string }) {
  const { regionId, region, regions, regionsStatus, setRegionId, refetchRegions } = useRegion();

  if (regionsStatus === "pending") {
    return (
      <Skeleton className={cn("h-9 w-48 bg-nav-accent", className)} aria-label="Loading regions" />
    );
  }
  if (regionsStatus === "error") {
    return (
      <Button
        variant="ghost"
        size="sm"
        onClick={refetchRegions}
        className={cn(
          "text-nav-foreground hover:bg-nav-accent hover:text-nav-foreground",
          className,
        )}
      >
        <MapPin aria-hidden="true" />
        Regions unavailable · Retry
      </Button>
    );
  }

  // Group by Maharashtra division (Part 10 R2.3), falling back to the district for a place
  // without one. Type-ahead (Radix Select) jumps to a place by its first letters.
  const groupOf = (r: (typeof regions)[number]) => r.division ?? r.district;
  const districts = [...new Set(regions.map(groupOf))];
  return (
    <Select value={regionId} onValueChange={setRegionId}>
      <SelectTrigger
        aria-label="Selected region"
        className={cn(
          "h-9 min-w-0 gap-2 border-nav-accent bg-nav-accent/60 text-nav-foreground shadow-none hover:bg-nav-accent focus-visible:ring-nav-muted/50 data-[placeholder]:text-nav-muted dark:bg-nav-accent/60 dark:hover:bg-nav-accent [&_svg:not([class*='text-'])]:text-nav-muted",
          className,
        )}
      >
        <MapPin aria-hidden="true" className="size-4 shrink-0" />
        <SelectValue placeholder="Choose a region">
          <span className="truncate sm:hidden">{region?.name ?? regionId}</span>
          <span className="hidden truncate sm:inline">{regionDisplayName(region, regionId)}</span>
        </SelectValue>
      </SelectTrigger>
      <SelectContent position="popper" align="end" className="min-w-56">
        {districts.map((district) => (
          <SelectGroup key={district}>
            <SelectLabel>{district}</SelectLabel>
            {regions
              .filter((r) => groupOf(r) === district)
              .map((r) => (
                <SelectItem key={r.id} value={r.id}>
                  {r.kind === "area" ? `${r.name} (area)` : r.name}
                  <span className="text-muted-foreground">· {r.district}</span>
                </SelectItem>
              ))}
          </SelectGroup>
        ))}
      </SelectContent>
    </Select>
  );
}
