import { describe, expect, it } from "vitest";
import { Catalog, CatalogError, loadPlaces, parsePlaces } from "./catalog.js";
import { repoPath } from "./config.js";

const city = (id: string, extra: Record<string, unknown> = {}) => ({
  id,
  name: id,
  district: "D",
  state: "Maharashtra",
  zone: "plains",
  lat: 20,
  lon: 77,
  ...extra,
});

describe("the committed config/regions.yaml", () => {
  const places = loadPlaces(repoPath("config/regions.yaml"));

  it("lists our proposed Maharashtra places: 14 cities and the 4 Mumbai areas", () => {
    expect(places).toHaveLength(18);
    expect(places.filter((p) => p.kind === "city")).toHaveLength(14);
    expect(places.filter((p) => p.kind === "area").map((p) => p.id)).toEqual([
      "kurla",
      "andheri",
      "dharavi",
      "colaba",
    ]);
    expect(new Set(places.map((p) => p.division))).toEqual(
      new Set(["Konkan", "Pune", "Nashik", "Chhatrapati Sambhajinagar", "Amravati", "Nagpur"]),
    );
  });

  it("keeps file order, which the selector and map use", () => {
    expect(places[0]!.id).toBe("mumbai");
    expect(new Catalog(places).inDivision("Nagpur").map((p) => p.id)).toEqual([
      "nagpur",
      "chandrapur",
    ]);
  });
});

describe("parsePlaces", () => {
  it("applies the defaults for entries without the Revision 2 fields", () => {
    const [place] = parsePlaces({ regions: [city("pune")] });
    expect(place).toMatchObject({ division: null, kind: "city", parent: null });
  });

  it.each([
    [[city("kurla", { kind: "area" })], /parent/],
    [[city("kurla", { kind: "area", parent: "atlantis" })], /parent/],
    [[city("mumbai"), city("pune", { parent: "mumbai" })], /cannot have a parent/],
    [[city("pune", { kind: "town" })], /kind/],
    [[city("pune"), city("pune")], /duplicate/],
    [[city("pune", { divison: "Pune" })], /divison|Unrecognized/i],
    [[city("Pune")], /id/],
  ])("rejects an invalid catalog (%#)", (regions, message) => {
    expect(() => parsePlaces({ regions })).toThrow(CatalogError);
    expect(() => parsePlaces({ regions })).toThrow(message);
  });

  it("rejects a document without a regions list", () => {
    expect(() => parsePlaces({})).toThrow(/regions/);
  });
});
