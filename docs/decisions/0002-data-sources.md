# ADR 0002 — Weather data sources and raw storage

**Status:** Accepted, 2026-09-28 (Part 02)

## Decisions

| Need | Choice | Why |
|------|--------|-----|
| Max temperature, and the history for the seasonal normal | **IMD gridded daily Tmax**, 1°×1°, binary `.GRD` per year, 1991 onwards | The authoritative Indian source. It is the only official IMD daily temperature product that is downloadable in bulk. IMD has no REST API for it. |
| IMD access path | HTTP POST to the IMD Pune download form, **plus a manual inbox fallback** (`IMD_INBOX_DIR`) | On 2026-09-28 the host failed its TLS handshake on some attempts and served files on others. The inbox means an unreachable IMD never blocks training. |
| Humidity, wind, solar radiation, precipitation (plus a second Tmax) | **NASA POWER daily point API**, `community=AG` | Public and keyless. It has every field the brief names, with a daily record from 1981. `AG` reports solar radiation in MJ/m²/day. |
| Forecast for the next 1–3 days | **Open-Meteo forecast API** | NASA POWER has no forecast product, and IMD publishes no machine-readable district forecast. Open-Meteo is public and keyless, and returns the same five daily fields. It is used **only** for live inference, never for training. |
| Working training dataset | **Synthetic, 5,000 records** (the brief's stated dataset) | Part 02 owns the landing format. Part 03 owns the generator and the labelling rule. A placeholder generator (`placeholder-v0`) exists only to prove the path end to end. |
| Raw storage | Parquet (tabular, canonical column names) **plus** the verbatim native payload, immutable, one file per chunk per run | Part 03 reads a single tabular shape without knowing any source API, and the native bytes stay available for audit and re-parsing. |
| Run metadata | Append-only JSON Lines log at `data/raw/_meta/ingestion_log.jsonl` | Human-readable, needs no database, and survives crashes: each event is flushed as it happens. |

## Alternatives rejected

- **`imdlib` (PyPI) for IMD**: it wraps the same HTTP form, but adds a dependency and hides the failure modes we need to log. The binary format is simple enough (float32 array) to read directly.
- **IMD station CSVs from a data portal**: these need registration or a licence, and have no stable programmatic path. Worth revisiting for production. See `docs/data/field-availability.md`.
- **Scraping the IMD city-forecast web pages**: brittle, possibly against the site's terms, and gives no humidity, radiation or wind forecast.
- **A CSV raw zone**: loses dtypes (dates, nullable floats) and is larger. Parquet is readable with one pandas call.

## Consequences

- None of the three sources needs an API key, so there are no weather-data secrets to rotate yet (see `docs/configuration-and-secrets.md`).
- IMD's grid is coarse: all five monitored Mumbai regions fall into only two IMD cells. NASA POWER has the same issue at about 0.5°. Real-data sub-city differentiation is therefore limited, as documented in the field-availability analysis.
- Wind height differs: NASA POWER reports wind at 2 m, Open-Meteo at 10 m. The raw data records `wind_height_m`, and Part 03 must reconcile the two before training/inference parity (Part 03 §6).
