/** Part 11 + R2: the Heatwave Command Center over a stubbed API (the real page, providers, router). */
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { SAMPLE_PREDICTION, SAMPLE_REGION } from "@/design/fixtures";
import type { PredictionOut, RegionOut, WeatherOut } from "@/lib/api/types";
import { okResponse, stubApi } from "@/test/http";
import { renderRoute } from "@/test/render";

const place = (id: string, name: string, extra: Partial<RegionOut> = {}): RegionOut => ({
  ...SAMPLE_REGION,
  id,
  name,
  district: name,
  division: "Konkan",
  kind: "city",
  parent: null,
  ...extra,
});
const REGIONS = [
  place("mumbai", "Mumbai"),
  place("kurla", "Kurla", { kind: "area", parent: "mumbai", lat: 19.07, lon: 72.88 }),
  place("nagpur", "Nagpur", { division: "Nagpur", zone: "plains", lat: 21.15, lon: 79.09 }),
  place("pune", "Pune", { division: "Pune", zone: "plains", lat: 18.52, lon: 73.86 }),
];
const READY = {
  ready: true,
  model_version: "m1",
  explainer_id: "e1",
  weather_data: "ok",
  weather_issued_at: null,
};

function prediction(regionId: string, risk: PredictionOut["risk_class"], lead = 0): PredictionOut {
  const region = REGIONS.find((r) => r.id === regionId)!;
  return {
    ...SAMPLE_PREDICTION,
    prediction_id: `pred_${regionId}${lead}`,
    created_at: new Date().toISOString(),
    region,
    risk_class: risk,
    confidence: risk === "NORMAL" ? 0.97 : 0.88,
    forecast_window: {
      ...SAMPLE_PREDICTION.forecast_window,
      lead_days: lead,
      valid_date: `2026-10-2${lead}`,
    },
  };
}
function weather(regionId: string, tmax: number, lead = 0): WeatherOut {
  return {
    region: REGIONS.find((r) => r.id === regionId)!,
    date: `2026-10-2${lead}`,
    lead_days: lead,
    tmax_c: tmax,
    normal_tmax_c: 33,
    temp_deviation_c: Math.round((tmax - 33) * 100) / 100,
    rh_pct: 60,
    wind_ms: 2,
    solar_mj_m2: 20,
    precip_mm: 0,
    provenance: {
      source: "open_meteo",
      issued_at: new Date().toISOString(),
      age_hours: 1,
      stale: false,
    },
  };
}

function stubDashboard(overrides: Record<string, unknown> = {}) {
  return stubApi({
    "GET /regions": REGIONS,
    "GET /health/ready": READY,
    "GET /predictions/latest-by-region": (url: URL) => {
      const lead = Number(url.searchParams.get("lead_days"));
      const items =
        lead === 2
          ? [prediction("mumbai", "HEATWAVE", 2)]
          : [prediction("mumbai", "NORMAL", lead), prediction("nagpur", "SEVERE_HEATWAVE", lead)];
      return okResponse({
        lead_days: lead,
        items,
        missing_region_ids: REGIONS.map((r) => r.id).filter(
          (id) => !items.some((p) => p.region.id === id),
        ),
      });
    },
    "GET /weather": (url: URL) => {
      const lead = Number(url.searchParams.get("lead_days"));
      return okResponse([
        weather("mumbai", 35.3 + lead, lead),
        weather("nagpur", 41.2, lead),
        weather("pune", 33.1, lead),
        weather("kurla", 35.9, lead),
      ]);
    },
    ...overrides,
  });
}

afterEach(() => vi.unstubAllGlobals());

describe("Heatwave Command Center", () => {
  it("fills the metric cards for the selected place from the API fields", async () => {
    stubDashboard();
    renderRoute("/");
    expect(
      await screen.findByRole("heading", { level: 1, name: "Heatwave Command Center" }),
    ).toBeInTheDocument();
    const temp = await screen.findByRole("region", { name: "Max temperature · Today" });
    await waitFor(() => expect(temp).toHaveTextContent("35.3 °C"));
    expect(temp).toHaveTextContent("+2.3 °C vs seasonal normal");
    const risk = screen.getByRole("region", { name: "Heatwave risk" });
    expect(within(risk).getByText("Normal")).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Prediction confidence" })).toHaveTextContent("97%");
    // Forecast card: the worst of leads 1-3 for Mumbai is HEATWAVE on lead 2.
    await waitFor(() =>
      expect(screen.getByRole("region", { name: "Forecast" })).toHaveTextContent(
        "Elevated heat risk: Heatwave",
      ),
    );
  });

  it("shows every place on the map and in the table, worst risk first", async () => {
    stubDashboard();
    renderRoute("/");
    const table = await screen.findByRole("table");
    await waitFor(() => expect(within(table).getAllByRole("row")).toHaveLength(5));
    const firstPlace = within(table).getAllByRole("row")[1]!;
    expect(firstPlace).toHaveTextContent("Nagpur");
    expect(firstPlace).toHaveTextContent("Severe Heatwave");
    expect(within(table).getByRole("button", { name: "Pune" }).closest("tr")).toHaveTextContent(
      "Not scored",
    );
    expect(
      screen.getByRole("button", { name: /^Nagpur, Nagpur division, Severe Heatwave/ }),
    ).toBeInTheDocument();
    expect(screen.getByRole("group", { name: "Mumbai areas" })).toBeInTheDocument();
  });

  it("selects a place from the table or the map and stays on the dashboard", async () => {
    stubDashboard();
    const { router } = renderRoute("/");
    const table = await screen.findByRole("table");
    await userEvent.click(await within(table).findByRole("button", { name: "Nagpur" }));
    await waitFor(() =>
      expect(screen.getByRole("combobox", { name: "Selected region" })).toHaveTextContent("Nagpur"),
    );
    expect(router.state.location.pathname).toBe("/");
    expect(
      within(screen.getByRole("region", { name: "Heatwave risk" })).getByText("Severe Heatwave"),
    ).toBeInTheDocument();
    // Inland place: the model caveat shows until step 10 validates the model there.
    expect(screen.getByRole("region", { name: "Prediction confidence" })).toHaveTextContent(
      "Model not yet validated for inland places",
    );
    await userEvent.click(screen.getByRole("button", { name: /^Mumbai, Konkan division/ }));
    await waitFor(() =>
      expect(screen.getByRole("combobox", { name: "Selected region" })).toHaveTextContent("Mumbai"),
    );
  });

  it("links each place to its Prediction page and its analysis", async () => {
    stubDashboard();
    renderRoute("/");
    const row = (
      await within(await screen.findByRole("table")).findByRole("button", { name: "Nagpur" })
    ).closest("tr")!;
    expect(within(row).getByRole("link", { name: "Details" })).toHaveAttribute(
      "href",
      "/predictions?region=nagpur",
    );
    expect(within(row).getByRole("link", { name: "Analyse" })).toHaveAttribute(
      "href",
      "/analytics?region=nagpur",
    );
  });

  it("compares two to four ticked places", async () => {
    stubDashboard();
    const { router } = renderRoute("/");
    const compare = await screen.findByRole("button", { name: "Compare" });
    expect(compare).toBeDisabled();
    await userEvent.click(await screen.findByRole("checkbox", { name: "Compare Nagpur" }));
    await userEvent.click(screen.getByRole("checkbox", { name: "Compare Pune" }));
    await userEvent.click(compare);
    // The Analytics route loads lazily: the location commits once its chunk arrives.
    await waitFor(() =>
      expect(`${router.state.location.pathname}${router.state.location.search}`).toBe(
        "/analytics?compare=nagpur,pune",
      ),
    );
  });

  it("switches the forecast day and asks the API for that lead", async () => {
    const fetchMock = stubDashboard();
    renderRoute("/");
    await userEvent.click(await screen.findByRole("button", { name: "In 3 days" }));
    await waitFor(() =>
      expect(screen.getByRole("region", { name: "Max temperature · In 3 days" })).toHaveTextContent(
        "38.3 °C",
      ),
    );
    const urls = fetchMock.mock.calls.map(([u]) => String(u));
    expect(urls.some((u) => u.includes("/weather?lead_days=3"))).toBe(true);
  });

  it("scores missing places only when asked, and says what happened", async () => {
    const fetchMock = stubDashboard({
      "POST /predictions/batch": { scored: 8, skipped: 0, predictions: [] },
    });
    renderRoute("/");
    const button = await screen.findByRole("button", {
      name: /Score 2 places without a prediction/,
    });
    expect(fetchMock.mock.calls.some(([, init]) => (init as RequestInit)?.method === "POST")).toBe(
      false,
    );
    await userEvent.click(button);
    expect(await screen.findByText("Scored 8 place-day pairs")).toBeInTheDocument();
    const post = fetchMock.mock.calls.find(
      ([u, init]) =>
        String(u).endsWith("/predictions/batch") && (init as RequestInit).method === "POST",
    )!;
    expect(JSON.parse(String((post[1] as RequestInit).body))).toEqual({ only_missing: true });
  });

  it("explains an empty start instead of showing a blank map", async () => {
    stubDashboard({
      "GET /predictions/latest-by-region": (url: URL) =>
        okResponse({
          lead_days: Number(url.searchParams.get("lead_days")),
          items: [],
          missing_region_ids: REGIONS.map((r) => r.id),
        }),
    });
    renderRoute("/");
    expect(await screen.findByText("No place has been scored yet")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Score 4 places without a prediction/ }),
    ).toBeInTheDocument();
    expect(screen.getAllByText("No prediction for this place yet").length).toBeGreaterThan(0);
  });

  it("recolours the map by forecast temperature with a data-derived legend", async () => {
    stubDashboard();
    renderRoute("/");
    await userEvent.click(await screen.findByRole("button", { name: "Forecast max temp" }));
    const legend = await screen.findByLabelText("Forecast max temperature legend");
    expect(legend).toHaveTextContent("33.0 °C");
    expect(legend).toHaveTextContent("42.0 °C");
    expect(legend).toHaveTextContent("Plains threshold 40.0 °C");
  });
});
