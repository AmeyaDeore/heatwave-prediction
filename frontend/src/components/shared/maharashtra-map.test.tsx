import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { SAMPLE_REGION } from "@/design/fixtures";
import {
  fitProjection,
  niceRange,
  RISK_SHAPE,
  scaleT,
  sequentialFill,
  type SequentialScale,
} from "@/design/map";
import type { RegionOut } from "@/lib/api/types";
import { MaharashtraMap } from "./maharashtra-map";

const place = (
  id: string,
  name: string,
  lat: number,
  lon: number,
  extra: Partial<RegionOut> = {},
): RegionOut => ({
  ...SAMPLE_REGION,
  id,
  name,
  district: name,
  lat,
  lon,
  division: "Konkan",
  kind: "city",
  parent: null,
  ...extra,
});

const PLACES = [
  place("mumbai", "Mumbai", 18.975, 72.8258),
  place("kurla", "Kurla", 19.0726, 72.8845, { kind: "area", parent: "mumbai" }),
  place("nagpur", "Nagpur", 21.1458, 79.0882, { division: "Nagpur", zone: "plains" }),
  place("pune", "Pune", 18.5204, 73.8567, { division: "Pune", zone: "plains" }),
];

describe("map geometry", () => {
  it("fits the box to the width and puts north at the top", () => {
    const p = fitProjection([72, 15, 81, 22], 600, 10);
    const [xw, yn] = p.project(72, 22);
    const [xe, ys] = p.project(81, 15);
    expect(xw).toBeCloseTo(10);
    expect(xe).toBeCloseTo(590);
    expect(yn).toBeLessThan(ys);
    expect(p.height).toBeGreaterThan(400); // 7° of latitude vs 9° × cos(18.5°) of longitude
  });

  it("derives a legend range from the data and clamps positions", () => {
    expect(niceRange([31.4, 36.6, 33])).toEqual({ min: 31, max: 37 });
    expect(niceRange([])).toEqual({ min: 0, max: 1 });
    const scale: SequentialScale = {
      kind: "sequential",
      label: "T",
      unit: "°C",
      min: 30,
      max: 40,
      format: String,
    };
    expect(scaleT(scale, 25)).toBe(0);
    expect(scaleT(scale, 35)).toBe(0.5);
    expect(scaleT(scale, 50)).toBe(1);
    expect(sequentialFill(0)).toContain("var(--tone-neutral)");
    expect(sequentialFill(1)).toContain("var(--tone-danger)");
  });

  it("gives every risk class its own marker shape (colour is never the only signal)", () => {
    expect(new Set(Object.values(RISK_SHAPE)).size).toBe(3);
  });
});

describe("MaharashtraMap", () => {
  const values = {
    mumbai: { risk: "NORMAL" as const, details: ["90% confidence"] },
    kurla: { risk: "HEATWAVE" as const },
    nagpur: { risk: "SEVERE_HEATWAVE" as const, stale: true },
  };

  it("draws a keyboard-reachable marker per place, Mumbai's areas in an inset", () => {
    render(
      <MaharashtraMap
        places={PLACES}
        values={values}
        scale={{ kind: "risk", label: "Predicted risk" }}
        title="Risk map"
      />,
    );
    const markers = screen.getAllByRole("button");
    expect(markers).toHaveLength(4);
    expect(markers.every((m) => m.getAttribute("tabindex") === "0")).toBe(true);
    const inset = screen.getByRole("group", { name: "Mumbai areas" });
    expect(within(inset).getByRole("button", { name: /Kurla/ })).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /^Nagpur, Nagpur division, Severe Heatwave, stale data/ }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /^Pune, Pune division, no prediction yet/ }),
    ).toBeInTheDocument();
  });

  it("selects with a click or with Enter, and marks the selection", async () => {
    const onSelect = vi.fn();
    const { rerender } = render(
      <MaharashtraMap
        places={PLACES}
        values={values}
        scale={{ kind: "risk", label: "Risk" }}
        title="Map"
        onSelect={onSelect}
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: /^Pune/ }));
    screen.getByRole("button", { name: /^Nagpur/ }).focus();
    await userEvent.keyboard("{Enter}");
    expect(onSelect.mock.calls).toEqual([["pune"], ["nagpur"]]);
    rerender(
      <MaharashtraMap
        places={PLACES}
        values={values}
        scale={{ kind: "risk", label: "Risk" }}
        title="Map"
        selectedId="nagpur"
      />,
    );
    expect(screen.getByRole("button", { name: /^Nagpur/ })).toHaveAttribute("aria-pressed", "true");
  });

  it("shows a tooltip on focus", () => {
    render(
      <MaharashtraMap
        places={PLACES}
        values={values}
        scale={{ kind: "risk", label: "Risk" }}
        title="Map"
      />,
    );
    fireEvent.focus(screen.getByRole("button", { name: /^Mumbai/ }));
    const tip = screen.getByRole("tooltip");
    expect(tip).toHaveTextContent("Mumbai");
    expect(tip).toHaveTextContent("Normal");
    expect(tip).toHaveTextContent("90% confidence");
  });

  it("colours by a sequential value with a legend from the data", () => {
    const scale: SequentialScale = {
      kind: "sequential",
      label: "Forecast max temperature",
      unit: "°C",
      min: 31,
      max: 37,
      format: (v) => `${v} °C`,
      marks: [{ value: 37, label: "Coastal threshold" }],
    };
    render(
      <MaharashtraMap
        places={PLACES}
        values={{ mumbai: { value: 34.2 }, pune: { value: null } }}
        scale={scale}
        title="Map"
      />,
    );
    expect(
      screen.getByRole("button", {
        name: /^Mumbai, Konkan division, Forecast max temperature 34.2 °C/,
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /^Pune, Pune division, no data/ }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Forecast max temperature legend")).toHaveTextContent(
      "Coastal threshold 37 °C",
    );
  });
});
