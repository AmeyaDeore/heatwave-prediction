/**
 * Monitored places, read from config/regions.yaml: the same file, and the same rules, as the
 * Python services (heatwave_ml.ingestion.regions). Revision 2 lists our proposed selection of
 * Maharashtra places. It is configuration, not an examiner-specified list.
 */
import { readFileSync } from "node:fs";
import { load } from "js-yaml";
import { z } from "zod";

const RegionId = z.string().regex(/^[a-z][a-z0-9_]{1,40}$/);

const placeSchema = z
  .object({
    id: RegionId,
    name: z.string().min(1),
    district: z.string().min(1),
    state: z.string().min(1),
    zone: z.string().min(1),
    lat: z.number().min(-90).max(90),
    lon: z.number().min(-180).max(180),
    division: z.string().min(1).nullable().default(null),
    kind: z.enum(["city", "area"]).default("city"),
    parent: RegionId.nullable().default(null),
  })
  // An unknown key is a typo, never ignored (the Python loaders raise on it too).
  .strict();

export type Place = z.output<typeof placeSchema>;

export class CatalogError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "CatalogError";
  }
}

/** Parse and check a regions document: valid entries, unique ids, a valid city/area tree. */
export function parsePlaces(document: unknown): Place[] {
  const raw = (document as { regions?: unknown } | null)?.regions;
  if (!Array.isArray(raw)) throw new CatalogError("regions.yaml has no 'regions' list");
  const places = raw.map((entry, i) => {
    const parsed = placeSchema.safeParse(entry);
    if (!parsed.success) {
      const issue = parsed.error.issues[0]!;
      throw new CatalogError(
        `regions.yaml entry ${i + 1}: ${issue.path.join(".") || "entry"}: ${issue.message}`,
      );
    }
    return parsed.data;
  });

  const byId = new Map<string, Place>();
  for (const place of places) {
    if (byId.has(place.id)) throw new CatalogError(`regions.yaml: duplicate id '${place.id}'`);
    byId.set(place.id, place);
  }
  for (const place of places) {
    if (place.kind === "area") {
      if (!place.parent || byId.get(place.parent)?.kind !== "city") {
        throw new CatalogError(
          `Region '${place.id}' is an area, so 'parent' must name a city in the same file`,
        );
      }
    } else if (place.parent !== null) {
      throw new CatalogError(`Region '${place.id}' is a city and cannot have a parent`);
    }
  }
  return places;
}

export function loadPlaces(path: string): Place[] {
  return parsePlaces(load(readFileSync(path, "utf8")));
}

/** Places keyed by id, keeping file order (the region selector and map list them so). */
export class Catalog {
  readonly byId: ReadonlyMap<string, Place>;

  constructor(readonly places: readonly Place[]) {
    this.byId = new Map(places.map((p) => [p.id, p]));
  }

  has(id: string): boolean {
    return this.byId.has(id);
  }

  inDivision(division: string | undefined): Place[] {
    return this.places.filter((p) => division === undefined || p.division === division);
  }
}
