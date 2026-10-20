import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { SAMPLE_REGION } from "@/design/fixtures";
import { errorResponse, okResponse, stubApi } from "@/test/http";
import { safeNext } from "@/app/navigation";
import { renderRoute } from "@/test/render";

const REGIONS = [
  SAMPLE_REGION,
  { ...SAMPLE_REGION, id: "kurla", name: "Kurla", district: "Mumbai Suburban" },
];
const READY = {
  ready: false,
  model_version: "xgboost-20260928T100821Z-0bde51",
  explainer_id: "x+shap",
  weather_data: "stale",
  weather_issued_at: null,
};

afterEach(() => vi.unstubAllGlobals());

function stubShell() {
  return stubApi({
    "GET /regions": REGIONS,
    "GET /health/ready": () => okResponse(READY, { status: 503 }),
  });
}

describe("navigation shell", () => {
  it("renders branding, then the four nav items in mockup order, then the region", async () => {
    stubShell();
    renderRoute("/");
    const banner = await screen.findByRole("banner");
    expect(within(banner).getByText("Climate Intelligence")).toBeInTheDocument();
    const nav = within(banner).getAllByRole("navigation", { name: "Primary" })[0]!;
    expect(
      within(nav)
        .getAllByRole("link")
        .map((a) => a.textContent),
    ).toEqual(["Dashboard", "Predictions", "Alerts", "Analytics"]);
    await waitFor(() =>
      expect(within(banner).getByRole("combobox", { name: "Selected region" })).toHaveTextContent(
        "Mumbai, Maharashtra",
      ),
    );
  });

  it("marks the current page and titles the document", async () => {
    stubShell();
    renderRoute("/alerts");
    expect(
      await screen.findByRole("heading", { level: 1, name: "Heatwave Early Warning" }),
    ).toBeInTheDocument();
    const [nav] = screen.getAllByRole("navigation", { name: "Primary" });
    expect(within(nav!).getByRole("link", { name: "Alerts" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(document.title).toBe("Alerts · Climate Intelligence");
  });

  it("shows 'last updated' on data screens only", async () => {
    stubShell();
    const { router } = renderRoute("/analytics");
    await screen.findByRole("heading", { level: 1, name: "Analytics" });
    expect(screen.getAllByRole("button", { name: "Refresh data" }).length).toBeGreaterThan(0);
    await router.navigate("/design-system");
    await screen.findByRole("heading", { level: 1, name: "Design system" });
    expect(screen.queryByRole("button", { name: "Refresh data" })).toBeNull();
  });

  it("selects a region from a ?region= link and cleans the URL", async () => {
    stubShell();
    const { router } = renderRoute("/predictions?region=kurla");
    await waitFor(() =>
      expect(screen.getByRole("combobox", { name: "Selected region" })).toHaveTextContent("Kurla"),
    );
    await waitFor(() => expect(router.state.location.search).toBe(""));
  });

  it("changes the global region from the selector", async () => {
    stubShell();
    renderRoute("/");
    const select = await screen.findByRole("combobox", { name: "Selected region" });
    await userEvent.click(select);
    await userEvent.click(await screen.findByRole("option", { name: /Kurla/ }));
    expect(select).toHaveTextContent("Kurla, Maharashtra");
    expect(screen.getByRole("heading", { level: 1 }).parentElement).toHaveTextContent(
      "Kurla, Maharashtra",
    );
  });

  it("warns when weather data is stale and shows the model version", async () => {
    stubShell();
    renderRoute("/");
    expect(await screen.findByText("Weather data stale")).toBeInTheDocument();
    expect(screen.getByText(/Model xgboost-20260928T100821Z-0bde51/)).toBeInTheDocument();
  });

  it("is keyboard navigable: skip link first, then the brand and nav", async () => {
    stubShell();
    renderRoute("/");
    await screen.findByRole("banner");
    await userEvent.tab();
    expect(document.activeElement).toHaveTextContent("Skip to content");
    await userEvent.tab();
    expect(document.activeElement).toHaveTextContent("Climate Intelligence");
    await userEvent.tab();
    expect(document.activeElement).toHaveTextContent("Dashboard");
  });

  it("keeps working when the region list fails, with a retry", async () => {
    stubApi({
      "GET /regions": () =>
        errorResponse(500, { kind: "internal", code: "INTERNAL_ERROR", message: "x" }),
      "GET /health/ready": READY,
    });
    renderRoute("/");
    expect(await screen.findByRole("button", { name: /Regions unavailable/ })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Heatwave Command Center");
  });
});

const TOKEN = {
  access_token: "tok",
  token_type: "bearer",
  expires_at: new Date(Date.now() + 3_600_000).toISOString(),
  user: { id: "u1", username: "official", display_name: "Demo Official", role: "official" },
};

describe("login (Revision 2: every page needs a session)", () => {
  it("sends a signed-out visit to /login and back to the page after signing in", async () => {
    const fetchMock = stubApi({
      "GET /regions": REGIONS,
      "GET /health/ready": READY,
      "POST /auth/login": TOKEN,
    });
    const { router } = renderRoute("/analytics?region=kurla", undefined, { signedIn: false });
    expect(await screen.findByRole("heading", { level: 2, name: "Sign in" })).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/login");
    expect(fetchMock).not.toHaveBeenCalled(); // nothing loads before signing in
    await userEvent.type(screen.getByLabelText("Username"), "official");
    await userEvent.type(screen.getByLabelText("Password"), "pw");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("heading", { level: 1, name: "Analytics" })).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByRole("combobox", { name: "Selected region" })).toHaveTextContent("Kurla"),
    );
  });

  it("says the same thing for any rejected sign-in", async () => {
    stubApi({
      "POST /auth/login": () =>
        errorResponse(401, {
          kind: "client",
          code: "UNAUTHORIZED",
          message: "Incorrect username or password.",
        }),
    });
    renderRoute("/login", undefined, { signedIn: false });
    await userEvent.type(await screen.findByLabelText("Username"), "official");
    await userEvent.type(screen.getByLabelText("Password"), "wrong");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Incorrect username or password.");
    expect(screen.getByLabelText("Password")).toHaveValue("");
  });

  it("explains a locked or rate-limited sign-in with the wait time", async () => {
    stubApi({
      "POST /auth/login": () =>
        errorResponse(
          429,
          { kind: "client", code: "RATE_LIMITED", message: "x" },
          { "Retry-After": "42" },
        ),
    });
    renderRoute("/login", undefined, { signedIn: false });
    await userEvent.type(await screen.findByLabelText("Username"), "official");
    await userEvent.type(screen.getByLabelText("Password"), "pw");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Try again in 42 seconds");
  });

  it("signs out on the server too, then shows the login page", async () => {
    const fetchMock = stubApi({
      "GET /regions": REGIONS,
      "GET /health/ready": READY,
      "POST /auth/logout": { signed_out: true },
    });
    const { router } = renderRoute("/");
    await userEvent.click(await screen.findByRole("button", { name: "Account: Demo Official" }));
    await userEvent.click(await screen.findByRole("menuitem", { name: /Sign out/ }));
    expect(await screen.findByText("You have signed out.")).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/login");
    const logout = fetchMock.mock.calls.find(([u]) => String(u).endsWith("/auth/logout"))!;
    expect((logout[1] as RequestInit).headers).toMatchObject({
      Authorization: "Bearer test-token",
    });
  });

  it("sends an already signed-in official from /login to the dashboard", async () => {
    stubShell();
    const { router } = renderRoute("/login");
    expect(
      await screen.findByRole("heading", { level: 1, name: "Heatwave Command Center" }),
    ).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/");
  });
});

describe("safeNext (no open redirect after sign-in)", () => {
  it.each([
    [null, "/"],
    ["/alerts?region=kurla", "/alerts?region=kurla"],
    ["https://evil.example", "/"],
    ["//evil.example", "/"],
    ["/login?next=/x", "/"],
  ])("%s → %s", (raw, expected) => {
    expect(safeNext(raw)).toBe(expected);
  });
});
