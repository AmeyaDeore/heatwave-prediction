/**
 * Geometry and scales for the Maharashtra map (Part 10 R2.2). Pure functions, so they are
 * unit-tested without rendering.
 *
 * Projection: equirectangular with the longitude scaled by cos(mean latitude). Over
 * Maharashtra's 6.4° of latitude that keeps shapes and distances within a few percent: enough
 * for a state map, with no projection library.
 */
import type { RiskClass } from "./labels";
import { riskCssVar } from "./tokens";

export type LonLat = [number, number];

export interface Projection {
  width: number;
  height: number;
  project: (lon: number, lat: number) => [number, number];
}

/** Fit [minLon, minLat, maxLon, maxLat] into a box `width` wide, keeping the aspect. */
export function fitProjection(
  bbox: [number, number, number, number],
  width: number,
  padding = 12,
): Projection {
  const [minLon, minLat, maxLon, maxLat] = bbox;
  const k = Math.cos((((minLat + maxLat) / 2) * Math.PI) / 180);
  const spanX = (maxLon - minLon) * k;
  const spanY = maxLat - minLat;
  const scale = (width - 2 * padding) / spanX;
  const height = Math.round(spanY * scale + 2 * padding);
  return {
    width,
    height,
    project: (lon, lat) => [
      padding + (lon - minLon) * k * scale,
      padding + (maxLat - lat) * scale, // north up
    ],
  };
}

/** SVG path data for GeoJSON polygon rings (each ring closed with Z). */
export function ringsToPath(polygons: LonLat[][][], projection: Projection): string {
  return polygons
    .flatMap((rings) =>
      rings.map(
        (ring) =>
          ring
            .map(([lon, lat], i) => {
              const [x, y] = projection.project(lon, lat);
              return `${i === 0 ? "M" : "L"}${x.toFixed(1)} ${y.toFixed(1)}`;
            })
            .join("") + "Z",
      ),
    )
    .join("");
}

/** Bounding box of a set of points, padded by `pad` degrees. */
export function bboxOf(points: LonLat[], pad: number): [number, number, number, number] {
  const lons = points.map((p) => p[0]);
  const lats = points.map((p) => p[1]);
  return [
    Math.min(...lons) - pad,
    Math.min(...lats) - pad,
    Math.max(...lons) + pad,
    Math.max(...lats) + pad,
  ];
}

// --- Scales --------------------------------------------------------------------------------

/** Marker shape per risk class: colour is never the only signal (Part 10 §5). */
export const RISK_SHAPE: Record<RiskClass, "circle" | "diamond" | "triangle"> = {
  NORMAL: "circle",
  HEATWAVE: "diamond",
  SEVERE_HEATWAVE: "triangle",
};

export function riskFill(riskClass: RiskClass): string {
  return riskCssVar(riskClass);
}

export interface SequentialScale {
  kind: "sequential";
  /** Legend title, e.g. "Forecast max temperature". */
  label: string;
  unit: string;
  min: number;
  max: number;
  /** Values the legend marks, e.g. the 4.5 °C / 6.5 °C departure thresholds. */
  marks?: { value: number; label: string }[];
  format: (value: number) => string;
}

export interface RiskScale {
  kind: "risk";
  label: string;
}

export type MapScale = RiskScale | SequentialScale;

/** 0..1 position of a value on a sequential scale, clamped. */
export function scaleT(scale: SequentialScale, value: number): number {
  if (scale.max === scale.min) return 1;
  return Math.max(0, Math.min(1, (value - scale.min) / (scale.max - scale.min)));
}

/**
 * Fill for a sequential value: a ramp through the design tokens (mid grey → amber → red), so
 * the map never uses a library palette. Mixed in OKLCH so the steps look even. The low end is
 * the mid-grey `--tone-neutral`, visible on the map in both themes (the subtle tint was not).
 */
export function sequentialFill(t: number): string {
  const pct = (x: number) => `${Math.round(x * 100)}%`;
  if (t <= 0.5) {
    return `color-mix(in oklch, var(--tone-warning) ${pct(t / 0.5)}, var(--tone-neutral))`;
  }
  return `color-mix(in oklch, var(--tone-danger) ${pct((t - 0.5) / 0.5)}, var(--tone-warning))`;
}

/** "Nice" bounds for a sequential legend from the data, never a fixed guess. */
export function niceRange(values: number[], step = 1): { min: number; max: number } {
  const finite = values.filter(Number.isFinite);
  if (finite.length === 0) return { min: 0, max: 1 };
  const min = Math.floor(Math.min(...finite) / step) * step;
  const max = Math.ceil(Math.max(...finite) / step) * step;
  return { min, max: max === min ? min + step : max };
}
