# config/geo/

Map geometry for the Maharashtra map (Part 10 R2.2, the teacher's mandatory Maharashtra map, M4).

| File | Contents | Source and licence |
|---|---|---|
| `maharashtra.geo.json` (GeoJSON; the `.json` extension lets the frontend import it directly) | Maharashtra state outline, one MultiPolygon, 585 points, 9.5 KB | **Natural Earth** 10m "Admin 1 – States, Provinces", v5.1.2 (`ne_10m_admin_1_states_provinces`, feature `adm0_a3 = IND`, `name = Maharashtra`). **Public domain** ([terms](https://www.naturalearthdata.com/about/terms-of-use/)); no permission or credit required. We credit it anyway |

**How it was made (2026-10-20):** downloaded from `github.com/nvkelso/natural-earth-vector` at tag `v5.1.2`, the Maharashtra feature extracted, simplified with Douglas–Peucker at 0.01° (about 1 km; 2,359 → 585 points) and coordinates rounded to 0.001°. No point was added or moved beyond that simplification. Bounding box 72.649–80.895 °E, 15.614–22.023 °N. All 18 monitored places in `config/regions.yaml` were checked to lie inside the outline.

**Not included: district boundaries.** Natural Earth has no Indian district (admin-2) layer, and we did not find a district file whose licence we could verify. So the map draws the state outline and one marker per place. Analysis views colour the place markers, not districts (Part 10 R2.2 deviation, recorded in the plan). A verified openly licensed district file can be added here later without changing the component's interface.
