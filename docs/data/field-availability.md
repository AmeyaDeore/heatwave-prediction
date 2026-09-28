# Field availability and gap analysis (Part 02 → Part 03)

**For:** the Part 03 owner (preprocessing and feature engineering). **Measured on:** real landed data, 2026-09-28. The numbers below come from `data/raw/`, not from documentation.

## 1. Which source supplies which field

| Field (brief) | IMD gridded | NASA POWER | Open-Meteo forecast | Synthetic |
|---|---|---|---|---|
| Maximum temperature | ✅ `tmax_c` (authoritative) | ✅ `tmax_c` (secondary) | ✅ `tmax_c` | ✅ |
| Seasonal normal temperature | ⚠️ **derived**: needs 30 yrs of IMD Tmax (1991–2020) | ⚠️ derivable (1981+), but see bias in §2.2 | ❌ | ✅ `normal_tmax_c` supplied directly |
| Relative humidity | ❌ | ✅ `rh_pct` (daily mean, 2 m) | ✅ `rh_pct` (daily mean, 2 m) | ✅ |
| Wind speed | ❌ | ✅ `wind_ms` at **2 m** | ✅ `wind_ms` at **10 m** | ✅ |
| Solar radiation | ❌ | ✅ `solar_mj_m2` | ✅ `solar_mj_m2` | ✅ |
| Precipitation | ❌ (IMD rainfall is a separate 0.25° product; not ingested) | ✅ `precip_mm` | ✅ `precip_mm` | ✅ |
| Forecast weather (next 1–3 days) | ❌ | ❌ (no forecast product) | ✅ `lead_days` 0–3 | n/a |

**Coverage landed so far:**
- NASA POWER: 2000-01-01 → 2024-12-31, 5 regions, 45,660 rows, **0 nulls** in any field.
- IMD: 1991 → 2024 complete (34 years × 5 regions = 62,095 rows, 0 nulls). The first bulk run was `partial` (4 years hit connection resets). A resumed run fetched only those 4 and skipped the 30 already landed.
- Open-Meteo: today + 3 days, 5 regions.
- Synthetic: 5,000 rows (placeholder generator).

## 2. Gaps and what Part 03 must decide

### 2.1 Seasonal normal is not a downloadable field
Neither IMD nor NASA POWER publishes a daily "seasonal normal" series. **Recommendation:** compute a day-of-year climatological mean of IMD `tmax_c` over 1991–2020 (the WMO standard 30-year period) per region, smoothed (for example a ±15-day window). Use the **same** normal table at training and at inference (Part 03 §6). That is why `IMD_HISTORY_START_YEAR=1991`.

### 2.2 Don't mix Tmax sources inside the deviation feature
Mumbai, 2023, both sources over 365 days: **NASA − IMD = +1.33 °C mean bias, MAE 1.99 °C, r = 0.84.** Temperature Deviation (Tmax − normal) must use a Tmax and a normal from the **same** source. Otherwise the bias alone reads as a +1.3 °C "anomaly", about a third of the HEATWAVE threshold of +4.5 °C. If IMD is missing for some dates, either leave them missing or bias-correct NASA against IMD over the overlap period. Do not silently fall back.

### 2.3 Spatial resolution: sub-city regions are not distinguishable in real history
| Source | Grid | Distinct series among the 5 regions |
|---|---|---|
| IMD | 1° (~110 km) | **2** (18.5/72.5 and 19.5/72.5), each 56–63 km from the region centroids, because nearer cells are sea |
| NASA POWER | ~0.5° | **1**: all five regions are identical |
| Open-Meteo forecast | ~0.1° | **3**: Colaba is about 3 °C cooler than Andheri/Kurla |

Consequences: (a) historical real data cannot teach region-specific behaviour, so Mumbai/Kurla/Andheri/Dharavi/Colaba differences at training time can only come from the synthetic set; (b) **inference sees finer spatial detail than training did**, which is a distribution shift that Part 05 should evaluate. Either treat region as a label only (not a feature), or add finer station data later (see §3).

### 2.4 Wind height mismatch (training 2 m vs inference 10 m)
NASA POWER wind is at 2 m and Open-Meteo wind is at 10 m. The raw data carries `wind_height_m`. Part 03 must convert one to the other before the train/inference feature parity step, for example with the FAO-56 log profile `u2 = u10 · 4.87 / ln(67.8·10 − 5.42) ≈ 0.748 · u10`.

### 2.5 "Recent observations" lag by 2–4 days
The NASA POWER recent window (fetched 2026-09-28) had nulls for the last 2 days in every field, and the last 4 days for solar radiation. Live inference must therefore take **today → +3 days from the forecast feed**, not from POWER. POWER's recent window is only useful as lagged context (for example "hot days in the past week").

### 2.6 Real heatwave days will be rare (coastal threshold vs Mumbai climate)
All five regions are `zone: coastal` (`config/risk_classes.yaml` then applies `min_tmax_celsius.coastal = 37`). In Mumbai's IMD cell, the 2023 monthly mean Tmax peaked at 34.6 °C (May). Real HEATWAVE and SEVERE_HEATWAVE days will be **rare** in the real history. Part 03's class-balance check should expect this, and it is one reason the brief uses a synthetic dataset.

### 2.7 IMD availability is unreliable
The IMD host failed TLS handshakes on some attempts and served files on others (2026-09-28). Pulls are resumable, and a manual inbox fallback exists (`docs/data/raw-landing-zone.md`). A failed IMD year appears in the log as `failed` with `retryable: true`. It never appears as a silently shorter dataset.

## 3. Production path (beyond the mini-project)
- IMD **station** observations (for example Santacruz and Colaba observatories) via the IMD Data Supply Portal would give genuinely distinct sub-city series and official station normals. This needs registration or a fee.
- IMD 0.25° gridded rainfall could replace NASA precipitation for India.

## 4. Handoff note (Part 02 → Part 03)

> Raw data available at: `data/raw/<source>/<chunk key>/<run_id>.parquet`, read with `RawLandingZone(...).read_latest(source)`. Contract: `docs/data/raw-landing-zone.md`. Sources implemented: IMD gridded Tmax (HTTP + manual inbox), NASA POWER (historical + recent), Open-Meteo forecast, synthetic (placeholder generator; Part 03 supplies the real one via `SyntheticAdapter(generator=...)`). Known field gaps: seasonal normal must be derived (§2.1); Tmax sources must not be mixed (§2.2); sub-city regions are indistinguishable in real history (§2.3); wind 2 m vs 10 m (§2.4); recent observations lag 2–4 days (§2.5). Location list config lives at: `config/regions.yaml`. Part 03 can now build preprocessing against this raw shape.
