# Synthetic dataset: generator `imd-sim-v1`

The brief's working dataset: **5,000 synthetic records generated using simulated IMD heatwave criteria**. The code is `heatwave_ml.preprocessing.synthetic.SyntheticGeneratorV1`, and it is landed through Part 02's `SyntheticAdapter`, so it gets the same immutable storage and run-log entry as real data. Labels follow [heatwave-labeling-spec.md](heatwave-labeling-spec.md).

```sh
uv run heatwave-prepare dataset            # lands the batch if needed, then builds data/heatwave_dataset.csv
uv run heatwave-ingest synthetic           # lands the batch only
```

## 1. Reproducibility

| Parameter | Value | Set by |
|---|---|---|
| Records | 5,000 | `SYNTHETIC_RECORD_COUNT` / `--count` |
| Seed | 42 | `RANDOM_SEED` / `--seed` |
| Date range | 2000-01-01 → 2024-12-31 | `TRAINING_START_DATE`, `TRAINING_END_DATE` |
| Regions | the five in `config/regions.yaml` | `MONITORED_REGIONS_FILE` |
| Normals | `config/seasonal_normals.csv` (SHA-256 in the manifest) | `SEASONAL_NORMALS_FILE` |
| Rule | `IMD-HW-DAILY-v1` | `config/risk_classes.yaml` |

The same parameters always give the same rows. That was verified on 2026-09-28: a rerun and a forced re-generation (`--force`) both reproduced `data/heatwave_dataset.csv` with SHA-256 `7412ab78…09ecd`. Landed at `data/raw/synthetic/generator=imd-sim-v1/seed=42-n=5000/`. **Change `version` in the class whenever the generation logic changes**, so a new batch lands under a new key instead of being confused with the old one. If the normals table changes, the dataset build refuses the old batch (the landed normals no longer match) and asks for `--force`.

## 2. Generation steps

1. **Slots.** Draw 4,980 distinct (region, date) pairs uniformly from 5 regions × 9,132 days, without replacement. The other 20 records are duplicates (step 7).
2. **Normal.** Look up `normal_tmax_c` from the committed IMD 1991–2020 table. This is the same lookup inference uses.
3. **True Tmax anomaly.**
   - *Background:* N(0, σₘ), where σₘ is the IMD 1991–2020 day-to-day std for that calendar month (1.1–2.3 °C).
   - *Heat event*, with probability pₘ: 2.5 °C + Gamma(2, 1.6) (mean 5.7 °C). pₘ is highest pre-monsoon (Mar–May 0.45–0.50), then Oct–Nov (0.30–0.35), winter (0.20–0.30), and lowest in the monsoon (Jun 0.12, Jul–Sep 0.03–0.05).
   - *Borderline placement* for 10 % of rows (498): the anomaly is set to within ±0.4 °C of a threshold the rule actually tests. That is either 4.5 or 6.5 °C departure where Tmax clears 37 °C, or Tmax ≈ 37 °C where that takes a believable 4.5–7.5 °C departure.
   - True Tmax = normal + anomaly, capped at 44 °C, rounded to 0.1 °C (IMD resolution).
4. **Label** = `classify(true Tmax, normal, zone)`. This is the rule itself, never an independent draw.
5. **Other variables**, from Mumbai's NASA POWER 2000–2024 monthly climatology (mean and std per month, in the code), shifted by the positive heat anomaly *h*:

   | Variable | Draw | Heat response | Why |
   |---|---|---|---|
   | `rh_pct` | N(RHₘ − 3.0·h, sdₘ), clipped 5–100 | drier | Mumbai heat spells come with dry easterly land winds |
   | `solar_mj_m2` | N(Sₘ + 0.5·h, sdₘ), clipped 0–32 | sunnier | clear skies |
   | `wind_ms` (2 m) | Gamma matching the month's mean/sd, × (1 − 0.03·h) | calmer | stagnant air |
   | `precip_mm` | rain with P = rain-day fractionₘ · e^(−0.6·h), amount Gamma(0.7) | drier | subsidence suppresses rain |

6. **Observed Tmax** = true Tmax + N(0, 0.3 °C) instrument noise. The dataset carries the observed value; the label came from the true one.
7. **Defects.**

   | Defect | Rate | Examples | Cleaning outcome |
   |---|---|---|---|
   | Missing value | 2 % each of RH, wind, solar, precip | NaN | imputed (fitted on train) |
   | Missing Tmax | 0.2 % | NaN | row dropped |
   | Just out of bounds | 0.5 % | RH 100.1–104.9, wind/solar/precip −0.01 to −0.4 | capped to the bound |
   | Gross error | 0.3 % | Tmax 99.9 (IMD sentinel), RH 999, wind −3, solar/precip −999 (POWER sentinel) | set missing, then dropped (Tmax) or imputed |
   | Duplicate record | 0.4 % (20) | re-landed region+date, half with a different RH reading | first copy kept |

## 3. Design decisions

**Heat events are enriched, deliberately.** Real Mumbai history has one heatwave date in 25 years ([labelling spec §7](heatwave-labeling-spec.md)). A model trained on real frequencies would never see the minority classes. The synthetic set therefore oversamples heat events so that HEATWAVE and SEVERE_HEATWAVE are each about 9–11 % of rows. They are still the minority, as the brief expects. Real-world prevalence is far lower, so Part 05 must not read synthetic precision as real-world precision, and should check false alarms on the real observed set (`data/processed/observed_dataset.parquet`).

**Labels come from the true Tmax; features carry the observed Tmax.** This is how real labelling works: the official label comes from station observations, while model inputs come from other instruments or grids. It gives the dataset a small, honest irreducible error near thresholds instead of a perfectly separable toy problem. Measured:

- **95.99 %** of rows get the same class when the rule is re-applied to the observed features.
- All 199 disagreeing rows sit within 1.02 °C of a threshold.
- Rows further than 1.5 °C from every threshold agree 100 % (a test asserts this).

**The Tmax ceiling is 44 °C.** Without it, the Gamma tail produced 50 °C+ days, which is not credible for a coastal city. The rule's absolute 45/47 °C branch therefore never fires in this dataset. It is covered by unit tests instead. For Mumbai it is irrelevant: the departure branch with the 37 °C coastal minimum decides every label.

**Region is not a feature.** Real history cannot tell the sub-city regions apart (field-availability §2.3). In the synthetic set, the regions differ only through their normals.

## 4. Result (seed 42, 5,000 records)

| | NORMAL | HEATWAVE | SEVERE_HEATWAVE | Rows |
|---|---|---|---|---|
| All (after cleaning) | 4,022 (80.96 %) | 521 (10.49 %) | 425 (8.55 %) | 4,968 |

A quick sanity check against the finished dataset, not a Part 04 result: an untuned Random Forest reaches 97.6 % validation accuracy (HEATWAVE recall 0.85), and Logistic Regression reaches 93.3 % (HEATWAVE recall 0.60). The data is learnable, not trivially separable, and harder for a linear model, because the rule's Tmax-minimum × departure interaction is non-linear.
