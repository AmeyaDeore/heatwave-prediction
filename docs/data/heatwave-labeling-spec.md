# Heatwave labelling rule: specification `IMD-HW-DAILY-v1`

**Status:** in force from 2026-09-28 (Part 03). **Code:** `heatwave_ml.features.criteria.classify`. **Thresholds:** `config/risk_classes.yaml`. This file specifies the rule; the YAML holds its numbers; the code is the one implementation. Every downstream metric (Part 05) and every SHAP "why" (Part 06) is relative to this rule.

## 1. Target

| | |
|---|---|
| Name | Heatwave Classification (`risk_class`) |
| Classes | `NORMAL`, `HEATWAVE`, `SEVERE_HEATWAVE`. Ordinal, encoded 0 / 1 / 2 in that order |
| Unit of labelling | one region on one calendar day |
| Inputs | `tmax_c` (daily maximum temperature, °C), `normal_tmax_c` (seasonal normal for that region and day, °C), the region's `zone` (`plains` / `coastal` / `hills`, from `config/regions.yaml`) |

## 2. Rule

Let **D** = Temperature Deviation = `round(tmax_c − normal_tmax_c, 2)`. Rounding to 0.01 °C keeps floating-point error from moving a value across a threshold: 41.1 − 36.6 is 4.500000000000004, and it counts as 4.5.

**Criterion A: departure from normal.** It applies only when `tmax_c ≥ min_tmax[zone]`:

| Condition | Class |
|---|---|
| D ≥ 6.5 | `SEVERE_HEATWAVE` |
| 4.5 ≤ D < 6.5 | `HEATWAVE` |
| otherwise | `NORMAL` |

**Criterion B: absolute maximum temperature.** It applies whatever the normal is:

| Condition | Class |
|---|---|
| `tmax_c` ≥ 47.0 | `SEVERE_HEATWAVE` |
| 45.0 ≤ `tmax_c` < 47.0 | `HEATWAVE` |

**Result:** the more severe of A and B.

| Zone | `min_tmax` |
|---|---|
| plains | 40.0 °C |
| coastal | 37.0 °C (all five monitored regions) |
| hills | 30.0 °C |

Every boundary is **inclusive** (≥). IMD words it as "departure 4.5 °C to 6.4 °C" and "> 6.4 °C". At IMD's 0.1 °C reporting resolution, that is the same as ≥ 4.5 and ≥ 6.5.

**Missing inputs:** if either `tmax_c` or `normal_tmax_c` is missing, the row is not labelled (`classify` raises). A missing Tmax never defaults to `NORMAL`.

## 3. Where the thresholds come from

They follow the India Meteorological Department's published heatwave criteria:

- A heatwave is considered once a station reaches 40 °C in the plains, 37 °C at coastal stations, or 30 °C in hilly regions.
- It is then declared on departure from normal (4.5–6.4 °C for a heatwave, above 6.4 °C for a severe heatwave) or on actual maximum temperature (≥ 45 °C, or ≥ 47 °C for severe).

The coastal clause (departure ≥ 4.5 °C with Tmax ≥ 37 °C) is the one that applies to Mumbai.

## 4. What v1 deliberately leaves out, and why

| IMD element | In v1? | Reason |
|---|---|---|
| Duration ("on 2 consecutive days") | **No** | v1 labels single days. Synthetic records are independent samples (no day-to-day sequence to count), and the model predicts one day at a time for the next 1–3 days. A duration condition belongs to the *alerting* layer (Part 09/13, for example "two consecutive HEATWAVE forecasts"), not to the daily label. |
| Spatial extent ("at ≥ 2 stations in a subdivision") | **No** | We label one region at a time; there is no station network to count. |
| Humidity / heat index | **No** | IMD's heatwave criteria are temperature-only; humidity drives separate "hot and humid" advisories. Relative humidity is still a model *feature*, and the model may learn its association with heat, but it does not change the label. |
| Warm-night criteria (minimum temperature) | **No** | No Tmin feature in the brief. |

## 5. Seasonal normal used by the rule

The rule is only as good as its normal. v1 uses one table, `config/seasonal_normals.csv`:

- mean IMD gridded Tmax per region and day of year over **1991–2020** (the WMO standard period),
- on a 366-day calendar,
- smoothed with a centred, circular ±15-day moving average.

The same table feeds the synthetic generator, the training features and live inference. Build it with `uv run heatwave-prepare normals`, from `heatwave_ml.features.normals.SeasonalNormals`. Its SHA-256 is recorded in the dataset manifest.

Note that all four "Mumbai City" and "Mumbai Suburban" regions map to only two IMD 1° cells (field-availability §2.3). Their normals are therefore identical in pairs:

- `mumbai` = `colaba`, peaking at 34.7 °C,
- `andheri` = `kurla` = `dharavi`, peaking at 36.3 °C.

## 6. Hand-checked examples (asserted in `ml/tests/test_features.py`)

| Tmax | Normal | Zone | D | Class | Why |
|---|---|---|---|---|---|
| 37.0 | 32.5 | coastal | 4.5 | HEATWAVE | both boundaries inclusive |
| 37.0 | 30.5 | coastal | 6.5 | SEVERE_HEATWAVE | departure exactly 6.5 |
| 36.9 | 30.0 | coastal | 6.9 | NORMAL | big departure, but below the coastal minimum |
| 38.0 | 33.6 | coastal | 4.4 | NORMAL | departure short by 0.1 |
| 41.1 | 36.6 | coastal | 4.5 | HEATWAVE | float rounding does not break the boundary |
| 40.0 | 35.5 | plains | 4.5 | HEATWAVE | plains minimum is 40 |
| 39.9 | 33.0 | plains | 6.9 | NORMAL | below the plains minimum |
| 45.0 | 43.0 | plains | 2.0 | HEATWAVE | absolute criterion |
| 47.0 | 45.0 | plains | 2.0 | SEVERE_HEATWAVE | absolute criterion |
| 45.5 | 38.5 | plains | 7.0 | SEVERE_HEATWAVE | absolute says HW, departure says severe: take the worse |

## 7. Consequence for Mumbai (read before interpreting any metric)

On the real observed set (IMD Tmax + NASA POWER, 2000–2024, 45,660 region-days), the rule fires on **one date**: 2002-10-07, a HEATWAVE (Tmax 37.05 °C, D = 4.57) in the one IMD cell shared by Andheri, Kurla and Dharavi, so it appears as 3 region-days. There are no SEVERE_HEATWAVE days. The highest Tmax was 39.5 °C and the largest departure 4.8 °C, never on the same day. Real Mumbai heatwaves under the coastal rule are extremely rare, which is why the training set is synthetic with an enriched heat-event rate (see [synthetic-dataset.md](synthetic-dataset.md)). Part 05 should report metrics on both:

- the synthetic test split, for class-wise precision and recall, and
- the real observed set, for the false-alarm rate on genuinely normal weather.

## 8. Versioning

`labeling_rule_version` in `config/risk_classes.yaml` names the rule in force. Change it (`…-v2`) whenever any threshold, the zone table, the rounding, or the normal-derivation method changes. The dataset manifest (`data/heatwave_dataset.manifest.json`) and, from Part 04 on, each model bundle record the version they were built with. Labels from different versions are not comparable.

| Version | Date | Change |
|---|---|---|
| `IMD-HW-DAILY-v1` | 2026-09-28 | Initial rule, as above |
