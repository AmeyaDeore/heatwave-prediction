/**
 * The Maharashtra map (Part 10 R2.2; the teacher's mandatory Maharashtra map, M4). Plain SVG
 * from config/geo/maharashtra.geo.json (Natural Earth, public domain): no map library, no
 * tiles, no network calls, every colour from the design tokens.
 *
 * The page decides what to show: it passes each place's value and a scale (categorical risk,
 * or sequential such as forecast temperature). Markers have a shape per risk class, a
 * tooltip on hover or focus, and are keyboard-selectable. A table equivalent is always rendered
 * by the page beside the map. The four Mumbai areas sit a few km apart, so they appear in a
 * Mumbai inset instead of overlapping on the state map.
 */
import { useId, useMemo, useState, type KeyboardEvent } from "react";
import boundary from "@config/geo/maharashtra.geo.json";
import { riskLabel, type RiskClass } from "@/design/labels";
import {
  bboxOf,
  fitProjection,
  ringsToPath,
  RISK_SHAPE,
  riskFill,
  scaleT,
  sequentialFill,
  type LonLat,
  type MapScale,
  type Projection,
} from "@/design/map";
import { RISK_CLASSES } from "@/design/labels";
import type { RegionOut } from "@/lib/api/types";
import { cn } from "@/lib/utils";

export interface MapValue {
  /** Categorical scale: the place's risk class. */
  risk?: RiskClass | null;
  /** Sequential scale: the number to colour by (null = no data). */
  value?: number | null;
  /** Data older than the freshness limit: drawn hollow, and said in the tooltip. */
  stale?: boolean;
  /** Extra tooltip lines, already formatted (probability, valid date, …). */
  details?: string[];
}

export interface MaharashtraMapProps {
  places: RegionOut[];
  values: Record<string, MapValue | undefined>;
  scale: MapScale;
  selectedId?: string | null;
  onSelect?: (id: string) => void;
  /** Accessible name of the map, e.g. "Predicted heatwave risk, today". */
  title: string;
  className?: string;
}

const polygons = boundary.features[0]!.geometry.coordinates as unknown as LonLat[][][];
const STATE_BBOX = boundary.bbox as [number, number, number, number];
const WIDTH = 640;
const INSET_WIDTH = 150;

function markerPath(shape: "circle" | "diamond" | "triangle", r: number): string {
  if (shape === "diamond") return `M0 ${-r * 1.25}L${r * 1.25} 0L0 ${r * 1.25}L${-r * 1.25} 0Z`;
  if (shape === "triangle")
    return `M0 ${-r * 1.35}L${r * 1.25} ${r * 0.95}L${-r * 1.25} ${r * 0.95}Z`;
  return `M${-r} 0a${r} ${r} 0 1 0 ${r * 2} 0a${r} ${r} 0 1 0 ${-r * 2} 0`;
}

function describe(place: RegionOut, value: MapValue | undefined, scale: MapScale): string {
  const where = [place.name, place.division ? `${place.division} division` : place.district];
  let what: string;
  if (scale.kind === "risk") {
    what = value?.risk ? riskLabel(value.risk) : "no prediction yet";
  } else {
    what = value?.value == null ? "no data" : `${scale.label} ${scale.format(value.value)}`;
  }
  return [...where, what, ...(value?.stale ? ["stale data"] : []), ...(value?.details ?? [])].join(
    ", ",
  );
}

interface MarkerProps {
  place: RegionOut;
  value: MapValue | undefined;
  scale: MapScale;
  projection: Projection;
  selected: boolean;
  onSelect?: (id: string) => void;
  onHover: (id: string | null) => void;
  radius: number;
  labelSide: "start" | "end";
}

function Marker({
  place,
  value,
  scale,
  projection,
  selected,
  onSelect,
  onHover,
  radius,
  labelSide,
}: MarkerProps) {
  const [x, y] = projection.project(place.lon, place.lat);
  const hasData = scale.kind === "risk" ? Boolean(value?.risk) : value?.value != null;
  const shape = scale.kind === "risk" && value?.risk ? RISK_SHAPE[value.risk] : "circle";
  const fill = !hasData
    ? "var(--card)"
    : scale.kind === "risk"
      ? riskFill(value!.risk!)
      : sequentialFill(scaleT(scale, value!.value!));
  const hollow = !hasData || value?.stale;
  const onKeyDown = (e: KeyboardEvent<SVGGElement>) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      onSelect?.(place.id);
    }
  };
  return (
    <g
      role="button"
      tabIndex={0}
      aria-label={describe(place, value, scale)}
      aria-pressed={selected}
      data-place={place.id}
      data-risk={value?.risk ?? undefined}
      transform={`translate(${x.toFixed(1)} ${y.toFixed(1)})`}
      className="cursor-pointer outline-none [&:focus-visible>.focus-ring]:opacity-100"
      onClick={() => onSelect?.(place.id)}
      onKeyDown={onKeyDown}
      onMouseEnter={() => onHover(place.id)}
      onMouseLeave={() => onHover(null)}
      onFocus={() => onHover(place.id)}
      onBlur={() => onHover(null)}
    >
      <circle
        className="focus-ring opacity-0"
        r={radius * 2.1}
        fill="none"
        stroke="var(--ring)"
        strokeWidth={2.5}
      />
      {selected && (
        <circle r={radius * 1.9} fill="none" stroke="var(--foreground)" strokeWidth={2} />
      )}
      <path
        d={markerPath(shape, radius)}
        fill={hollow ? "var(--card)" : fill}
        stroke={hasData ? (hollow ? fill : "var(--card)") : "var(--muted-foreground)"}
        strokeWidth={hollow ? 2.5 : 1.5}
        strokeDasharray={hasData ? undefined : "2 2"}
      />
      <text
        x={labelSide === "start" ? radius + 5 : -(radius + 5)}
        y={4}
        textAnchor={labelSide}
        className={cn("fill-foreground text-[11px]", selected ? "font-semibold" : "font-medium")}
        style={{ paintOrder: "stroke", stroke: "var(--card)", strokeWidth: 3 }}
      >
        {place.name}
      </text>
    </g>
  );
}

function Legend({ scale }: { scale: MapScale }) {
  if (scale.kind === "risk") {
    return (
      <ul
        className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground"
        aria-label={`${scale.label} legend`}
      >
        {RISK_CLASSES.map((rc) => (
          <li key={rc} className="inline-flex items-center gap-1.5">
            <svg width="14" height="14" viewBox="-7 -7 14 14" aria-hidden="true">
              <path d={markerPath(RISK_SHAPE[rc], 4.5)} fill={riskFill(rc)} />
            </svg>
            {riskLabel(rc)}
          </li>
        ))}
        <li className="inline-flex items-center gap-1.5">
          <svg width="14" height="14" viewBox="-7 -7 14 14" aria-hidden="true">
            <path
              d={markerPath("circle", 4.5)}
              fill="var(--card)"
              stroke="var(--muted-foreground)"
              strokeDasharray="2 2"
            />
          </svg>
          No prediction yet
        </li>
        <li className="inline-flex items-center gap-1.5">
          <svg width="14" height="14" viewBox="-7 -7 14 14" aria-hidden="true">
            <path
              d={markerPath("circle", 4.5)}
              fill="var(--card)"
              stroke={riskFill("HEATWAVE")}
              strokeWidth="2"
            />
          </svg>
          Hollow = stale data
        </li>
      </ul>
    );
  }
  const steps = [0, 0.25, 0.5, 0.75, 1];
  return (
    <div
      className="flex flex-col gap-1 text-xs text-muted-foreground"
      aria-label={`${scale.label} legend`}
    >
      <span className="font-medium text-foreground">{scale.label}</span>
      <div className="flex items-center gap-2">
        <span className="tabular">{scale.format(scale.min)}</span>
        <span className="flex h-2.5 w-40 overflow-hidden rounded-full" aria-hidden="true">
          {steps.map((t) => (
            <span key={t} className="flex-1" style={{ background: sequentialFill(t) }} />
          ))}
        </span>
        <span className="tabular">{scale.format(scale.max)}</span>
      </div>
      {scale.marks?.length ? (
        <span>{scale.marks.map((m) => `${m.label} ${scale.format(m.value)}`).join(" · ")}</span>
      ) : null}
    </div>
  );
}

export function MaharashtraMap({
  places,
  values,
  scale,
  selectedId,
  onSelect,
  title,
  className,
}: MaharashtraMapProps) {
  const titleId = useId();
  const [hovered, setHovered] = useState<string | null>(null);
  const main = useMemo(() => fitProjection(STATE_BBOX, WIDTH), []);
  const outline = useMemo(() => ringsToPath(polygons, main), [main]);

  const cities = places.filter((p) => p.kind !== "area");
  const areas = places.filter((p) => p.kind === "area");
  const insetParent = areas.length ? places.find((p) => p.id === areas[0]!.parent) : undefined;
  const insetPlaces = insetParent ? [insetParent, ...areas] : [];
  // Cheap (five points), so not memoised.
  const inset = insetPlaces.length
    ? fitProjection(
        bboxOf(
          insetPlaces.map((p) => [p.lon, p.lat]),
          0.05,
        ),
        INSET_WIDTH,
        10,
      )
    : null;

  const tooltipPlace = places.find((p) => p.id === hovered);
  const markerProps = (
    place: RegionOut,
    projection: Projection,
    radius: number,
    labelSide: "start" | "end",
  ) => ({
    place,
    value: values[place.id],
    scale,
    projection,
    selected: place.id === selectedId,
    onSelect,
    onHover: setHovered,
    radius,
    labelSide,
  });

  return (
    <figure className={cn("flex flex-col gap-3", className)} aria-labelledby={titleId}>
      <figcaption id={titleId} className="sr-only">
        {title}. Use Tab to move between places and Enter to select one. A table with the same data
        follows the map.
      </figcaption>
      <div className="relative">
        <svg
          viewBox={`0 0 ${main.width} ${main.height}`}
          className="h-auto w-full"
          role="group"
          aria-label={title}
        >
          <path d={outline} fill="var(--muted)" stroke="var(--border)" strokeWidth={1.5} />
          {cities.map((place) => (
            <Marker
              key={place.id}
              {...markerProps(
                place,
                main,
                6,
                // Labels to the right, except at the far east edge where they would clip.
                place.lon > 80 ? "end" : "start",
              )}
            />
          ))}
        </svg>

        {inset && insetParent && (
          // Below the map on phones; from sm up, bottom-right (outside the south-east edge), so the
          // inset never covers a place.
          <div className="mt-2 w-fit rounded-lg border bg-card/95 p-1.5 shadow-xs sm:absolute sm:right-2 sm:bottom-2 sm:mt-0">
            <p className="px-1 text-[10px] font-semibold tracking-wide text-muted-foreground uppercase">
              {insetParent.name} areas
            </p>
            <svg
              viewBox={`0 0 ${inset.width} ${inset.height}`}
              width={INSET_WIDTH}
              role="group"
              aria-label={`${insetParent.name} areas`}
            >
              {areas.map((place) => (
                <Marker
                  key={place.id}
                  {...markerProps(place, inset, 5, place.lon < 72.86 ? "end" : "start")}
                />
              ))}
            </svg>
          </div>
        )}

        {tooltipPlace && (
          <div
            role="tooltip"
            className="pointer-events-none absolute top-2 right-2 max-w-64 rounded-md border bg-popover px-3 py-2 text-xs text-popover-foreground shadow-md"
          >
            <p className="font-semibold">{tooltipPlace.name}</p>
            <p className="text-muted-foreground">
              {tooltipPlace.division ? `${tooltipPlace.division} division` : tooltipPlace.district}
            </p>
            {describe(tooltipPlace, values[tooltipPlace.id], scale)
              .split(", ")
              .slice(2)
              .map((line) => (
                <p key={line}>{line}</p>
              ))}
          </div>
        )}
      </div>
      <Legend scale={scale} />
    </figure>
  );
}
