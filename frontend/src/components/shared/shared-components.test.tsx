import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { SAMPLE_FACTORS } from "@/design/fixtures";
import { ApiError } from "@/lib/api/errors";
import { renderWithProviders } from "@/test/render";
import { ActionList } from "./action-list";
import { ContributingFactorBar, FactorList } from "./contributing-factor-bar";
import { DataSourceTag } from "./data-source-tag";
import { MetricCard } from "./metric-card";
import { RiskBadge } from "./risk-badge";
import { QueryState } from "./states";
import { StatusPill } from "./status-pill";

const byFeature = (f: string) => SAMPLE_FACTORS.find((x) => x.feature === f)!;

describe("RiskBadge", () => {
  it.each([
    ["NORMAL", "Normal", "bg-tone-success-subtle"],
    ["HEATWAVE", "Heatwave", "bg-tone-warning-subtle"],
    ["SEVERE_HEATWAVE", "Severe Heatwave", "bg-tone-danger-subtle"],
  ] as const)("%s shows its config label and its one colour", (risk, label, cls) => {
    renderWithProviders(<RiskBadge riskClass={risk} />);
    const badge = screen.getByText(label);
    expect(badge).toHaveAttribute("data-risk", risk);
    expect(badge.className).toContain(cls);
    expect(badge.querySelector("svg")).not.toBeNull(); // colour is never the only signal
  });
});

describe("StatusPill", () => {
  it("shows the status word with a description for screen readers", () => {
    renderWithProviders(<StatusPill status="PENDING" />);
    const pill = screen.getByText("PENDING").closest("[data-slot=status-pill]")!;
    expect(pill.className).toContain("bg-tone-warning-subtle");
    expect(pill).toHaveTextContent("Delivery in progress.");
  });

  it("makes a pill with a failure reason focusable so keyboard users can read it", async () => {
    renderWithProviders(<StatusPill status="FAILED" detail="1 of 2 email recipients failed" />);
    await userEvent.tab();
    expect(document.activeElement).toHaveTextContent("FAILED");
    expect(document.activeElement).toHaveTextContent("1 of 2 email recipients failed");
  });
});

describe("ContributingFactorBar", () => {
  it("draws a risk-raising factor to the right, in amber, with the API's signed share", () => {
    const { container } = renderWithProviders(
      <ContributingFactorBar factor={byFeature("temp_deviation_c")} />,
    );
    expect(screen.getByText("+65.0%")).toBeInTheDocument();
    expect(screen.getByText("+8.0 °C")).toBeInTheDocument(); // display_value, unchanged
    const [left, right] = container.querySelectorAll("[aria-hidden=true].grid-cols-2 > div");
    expect(left!.children).toHaveLength(0);
    expect((right!.firstElementChild as HTMLElement).style.width).toBe("65%");
    expect(right!.firstElementChild!.className).toContain("bg-tone-warning");
  });

  it("draws a protective (negative) factor to the left, in blue (Part 12 §4 edge case)", () => {
    const { container } = renderWithProviders(
      <ContributingFactorBar factor={byFeature("wind_ms")} />,
    );
    expect(screen.getByText("-2.0%")).toBeInTheDocument();
    expect(screen.getByText(/lowers heat risk/)).toBeInTheDocument();
    const [left, right] = container.querySelectorAll("[aria-hidden=true].grid-cols-2 > div");
    expect(right!.children).toHaveLength(0);
    expect((left!.firstElementChild as HTMLElement).style.width).toBe("2%");
    expect(left!.firstElementChild!.className).toContain("bg-tone-info");
  });

  it("marks an imputed input as estimated", () => {
    renderWithProviders(<ContributingFactorBar factor={byFeature("rh_pct")} />);
    expect(screen.getByRole("button", { name: /estimated/i })).toBeInTheDocument();
  });

  it("lists factors by rank and honours the dashboard's top-N limit", () => {
    const shuffled = [...SAMPLE_FACTORS].reverse();
    renderWithProviders(<FactorList factors={shuffled} limit={3} />);
    const items = within(screen.getByRole("list", { name: /contributing factors/i })).getAllByRole(
      "listitem",
    );
    expect(items.map((li) => li.textContent?.split(/\d/)[0])).toEqual([
      "Temperature Deviation+",
      "Maximum Temperature",
      "Wind Speed",
    ]);
  });
});

describe("ActionList", () => {
  it("numbers the API's actions in order", () => {
    renderWithProviders(
      <ActionList actions={["Issue ward-level heat advisory", "Something brand new"]} />,
    );
    const items = screen.getAllByRole("listitem");
    expect(items[0]).toHaveTextContent("1Issue ward-level heat advisory");
    expect(items[1]).toHaveTextContent("2Something brand new"); // unknown wording still renders
  });
});

describe("MetricCard and DataSourceTag", () => {
  it("renders label, value, delta and tags; shows a skeleton while loading", () => {
    const { rerender } = renderWithProviders(
      <MetricCard
        label="Current Temperature"
        value="42.6 °C"
        delta={{ text: "+8.0 °C above seasonal normal", direction: "up", tone: "danger" }}
        tags={<DataSourceTag kind="demo" />}
      />,
    );
    const card = screen.getByRole("region", { name: "Current Temperature" });
    expect(card).toHaveTextContent("42.6 °C");
    expect(card).toHaveTextContent("+8.0 °C above seasonal normal");
    expect(card).toHaveTextContent("Demo data");
    rerender(<MetricCard label="Current Temperature" value="42.6 °C" loading />);
    expect(screen.getByRole("region", { name: "Current Temperature" })).toHaveAttribute(
      "aria-busy",
      "true",
    );
  });
});

describe("QueryState (§6 conventions)", () => {
  const base = {
    data: undefined,
    error: null,
    isPending: false,
    isError: false,
    isFetching: false,
    refetch: vi.fn(),
  };

  it("shows a loading placeholder, not a blank card", () => {
    renderWithProviders(
      <QueryState query={{ ...base, isPending: true }}>{() => "content"}</QueryState>,
    );
    expect(screen.getByRole("status")).toHaveTextContent("Loading");
  });

  it("shows a plain-language error with a working retry", async () => {
    const refetch = vi.fn();
    const error = new ApiError({
      kind: "upstream",
      code: "WEATHER_DATA_UNAVAILABLE",
      message: "x",
      status: 503,
      requestId: "abc123",
    });
    renderWithProviders(
      <QueryState query={{ ...base, isError: true, error, refetch }}>{() => "content"}</QueryState>,
    );
    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("Weather data is unavailable");
    expect(alert).toHaveTextContent("abc123");
    expect(alert).not.toHaveTextContent("WEATHER_DATA_UNAVAILABLE");
    await userEvent.click(screen.getByRole("button", { name: /try again/i }));
    expect(refetch).toHaveBeenCalledOnce();
  });

  it("can treat a 404 as empty (no prediction made yet)", () => {
    const error = new ApiError({
      kind: "client",
      code: "NOT_FOUND",
      message: "None yet.",
      status: 404,
    });
    renderWithProviders(
      <QueryState
        query={{ ...base, isError: true, error }}
        notFoundAsEmpty
        empty={<p>No prediction yet</p>}
      >
        {() => "content"}
      </QueryState>,
    );
    expect(screen.getByText("No prediction yet")).toBeInTheDocument();
  });

  it("keeps showing data when a background refetch fails (stale but visible)", () => {
    const error = new ApiError({ kind: "network", code: "NETWORK_ERROR", message: "x", status: 0 });
    renderWithProviders(
      <QueryState query={{ ...base, data: [1, 2], isError: true, error }}>
        {(d) => `items:${d.length}`}
      </QueryState>,
    );
    expect(screen.getByText("items:2")).toBeInTheDocument();
  });

  it("shows the empty state when the data is empty", () => {
    renderWithProviders(
      <QueryState
        query={{ ...base, data: [] as number[] }}
        isEmpty={(d) => d.length === 0}
        empty={<p>Nothing</p>}
      >
        {() => "content"}
      </QueryState>,
    );
    expect(screen.getByText("Nothing")).toBeInTheDocument();
  });
});
