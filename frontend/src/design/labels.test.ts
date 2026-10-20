import vectors from "@/test/python-format-vectors.json";
import { describe, expect, it } from "vitest";
import table from "@config/feature_labels.json";
import {
  formatFeatureValue,
  formatFixed,
  formatProbability,
  RISK_CLASSES,
  RISK_LABELS,
  riskLabel,
} from "./labels";

describe("shared label table", () => {
  it("uses exactly the three risk classes, labelled from config/feature_labels.json", () => {
    expect(Object.keys(table.risk_classes).sort()).toEqual([...RISK_CLASSES].sort());
    expect(riskLabel("SEVERE_HEATWAVE")).toBe("Severe Heatwave");
    expect(RISK_LABELS).toBe(table.risk_classes);
  });
});

describe("formatting parity with the Python explainer (summary.py)", () => {
  it.each(vectors.values as [string, number, string][])(
    "formatFeatureValue(%s, %s) === %s",
    (feature, value, expected) => {
      expect(formatFeatureValue(feature, value)).toBe(expected);
    },
  );

  it.each(vectors.probabilities as [number, string][])(
    "formatProbability(%s) === %s",
    (p, expected) => {
      expect(formatProbability(p)).toBe(expected);
    },
  );

  it("rounds exact binary ties to even, like Python, and other values normally", () => {
    expect(formatFixed(31.25, 1)).toBe("31.2"); // exact tie -> even
    expect(formatFixed(31.75, 1)).toBe("31.8"); // exact tie -> even
    expect(formatFixed(0.125, 2)).toBe("0.12");
    expect(formatFixed(2.45, 1)).toBe("2.5"); // 2.45 is stored as 2.4500000000000001776...
    expect(formatFixed(-0.04, 1)).toBe("-0.0");
  });

  it("shows a dash for a missing input instead of inventing a value", () => {
    expect(formatFeatureValue("rh_pct", null)).toBe("—");
    expect(formatFeatureValue("rh_pct", undefined)).toBe("—");
  });
});
