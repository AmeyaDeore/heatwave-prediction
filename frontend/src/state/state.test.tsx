import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AppProviders } from "@/app/providers";
import { SAMPLE_REGION } from "@/design/fixtures";
import { ApiError } from "@/lib/api/errors";
import { stubApi } from "@/test/http";
import { seedSession, testQueryClient } from "@/test/render";
import { useRegion, withRegion } from "./region-context";
import { useSession } from "./session-context";

const REGIONS = [
  SAMPLE_REGION,
  { ...SAMPLE_REGION, id: "kurla", name: "Kurla", district: "Mumbai Suburban" },
];

const wrapper = ({ children }: { children: ReactNode }) => (
  <AppProviders client={testQueryClient()}>{children}</AppProviders>
);

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
  window.history.replaceState(null, "", "/");
});

describe("selected region (global, persistent)", () => {
  beforeEach(() => seedSession()); // Revision 2: the region list needs a session

  it("defaults to VITE_DEFAULT_REGION and persists a change", async () => {
    stubApi({ "GET /regions": REGIONS });
    const { result } = renderHook(() => useRegion(), { wrapper });
    expect(result.current.regionId).toBe("mumbai");
    await waitFor(() => expect(result.current.region?.name).toBe("Mumbai"));
    act(() => result.current.setRegionId("kurla"));
    expect(result.current.regionId).toBe("kurla");
    expect(JSON.parse(localStorage.getItem("hw.region")!)).toBe("kurla");
  });

  it("prefers ?region= over the stored choice (drill-through links)", () => {
    stubApi({ "GET /regions": REGIONS });
    localStorage.setItem("hw.region", JSON.stringify("mumbai"));
    window.history.replaceState(null, "", "/predictions?region=kurla");
    const { result } = renderHook(() => useRegion(), { wrapper });
    expect(result.current.regionId).toBe("kurla");
  });

  it("repairs an id that no longer exists once the region list loads", async () => {
    stubApi({ "GET /regions": REGIONS });
    localStorage.setItem("hw.region", JSON.stringify("atlantis"));
    const { result } = renderHook(() => useRegion(), { wrapper });
    expect(result.current.regionId).toBe("atlantis"); // queries start immediately
    await waitFor(() => expect(result.current.regionId).toBe("mumbai"));
  });

  it("ignores ids that can't be region ids", () => {
    stubApi({ "GET /regions": REGIONS });
    const { result } = renderHook(() => useRegion(), { wrapper });
    act(() => result.current.setRegionId("../../etc"));
    expect(result.current.regionId).toBe("mumbai");
  });

  it("builds drill-through links", () => {
    expect(withRegion("/predictions", "kurla")).toBe("/predictions?region=kurla");
    expect(withRegion("/analytics?days=7", "colaba")).toBe("/analytics?days=7&region=colaba");
  });
});

describe("session", () => {
  const user = { id: "u1", username: "official", display_name: "Demo Official", role: "official" };
  const token = (minutes: number) => ({
    access_token: "tok",
    token_type: "bearer",
    expires_at: new Date(Date.now() + minutes * 60_000).toISOString(),
    user,
  });

  it("signs in, keeps the token for the tab only, and signs out", async () => {
    stubApi({ "GET /regions": REGIONS, "POST /auth/login": token(60) });
    const { result } = renderHook(() => useSession(), { wrapper });
    expect(result.current.isAuthenticated).toBe(false);
    await act(() => result.current.signIn("official", "pw"));
    expect(result.current.user?.display_name).toBe("Demo Official");
    expect(sessionStorage.getItem("hw.session")).toContain("tok");
    expect(localStorage.getItem("hw.session")).toBeNull();
    act(() => result.current.signOut());
    expect(result.current.isAuthenticated).toBe(false);
    expect(sessionStorage.getItem("hw.session")).toBeNull();
  });

  it("ignores an expired stored session", () => {
    stubApi({ "GET /regions": REGIONS });
    sessionStorage.setItem(
      "hw.session",
      JSON.stringify({ token: "old", expiresAt: new Date(Date.now() - 1_000).toISOString(), user }),
    );
    const { result } = renderHook(() => useSession(), { wrapper });
    expect(result.current.isAuthenticated).toBe(false);
  });

  it("ends the session exactly at expires_at", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    stubApi({ "GET /regions": REGIONS, "POST /auth/login": token(1) });
    const { result } = renderHook(() => useSession(), { wrapper });
    await act(() => result.current.signIn("official", "pw"));
    await act(() => vi.advanceTimersByTimeAsync(61_000));
    expect(result.current.isAuthenticated).toBe(false);
    expect(result.current.endedReason).toBe("expired");
  });

  it("withToken: signed out → opens sign-in and rejects with 401, never calls the API", async () => {
    stubApi({ "GET /regions": REGIONS });
    const { result } = renderHook(() => useSession(), { wrapper });
    const call = vi.fn();
    await act(async () => {
      await expect(result.current.withToken(call)).rejects.toMatchObject({ status: 401 });
    });
    expect(call).not.toHaveBeenCalled();
    expect(result.current.signInOpen).toBe(true);
  });

  it("withToken: a 401 from the API ends the session and asks to sign in again", async () => {
    stubApi({ "GET /regions": REGIONS, "POST /auth/login": token(60) });
    const { result } = renderHook(() => useSession(), { wrapper });
    await act(() => result.current.signIn("official", "pw"));
    const expired = new ApiError({
      kind: "client",
      code: "UNAUTHORIZED",
      message: "x",
      status: 401,
    });
    await act(async () => {
      await expect(result.current.withToken(() => Promise.reject(expired))).rejects.toBe(expired);
    });
    expect(result.current.isAuthenticated).toBe(false);
    expect(result.current.endedReason).toBe("expired");
    expect(result.current.signInOpen).toBe(true);
  });

  it("passes the current token to protected calls", async () => {
    stubApi({ "GET /regions": REGIONS, "POST /auth/login": token(60) });
    const { result } = renderHook(() => useSession(), { wrapper });
    await act(() => result.current.signIn("official", "pw"));
    await expect(result.current.withToken(async (t) => t)).resolves.toBe("tok");
  });
});

describe("session bridge (Revision 2: every call carries the session)", () => {
  it("does not load the region list until an official signs in", async () => {
    const fetchMock = stubApi({ "GET /regions": REGIONS });
    const { result } = renderHook(() => useRegion(), { wrapper });
    await new Promise((r) => setTimeout(r, 50));
    expect(fetchMock).not.toHaveBeenCalled();
    expect(result.current.regions).toEqual([]);
  });

  it("attaches the session's token to ordinary reads", async () => {
    seedSession();
    const fetchMock = stubApi({ "GET /regions": REGIONS });
    renderHook(() => useRegion(), { wrapper });
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const init = fetchMock.mock.calls[0]![1] as RequestInit;
    expect((init.headers as Record<string, string>).Authorization).toBe("Bearer test-token");
  });

  it("ends the session as expired when a read comes back 401", async () => {
    seedSession();
    stubApi({
      "GET /regions": () =>
        new Response(
          JSON.stringify({
            status: "error",
            error: {
              kind: "client",
              code: "UNAUTHORIZED",
              message: "Sign in to continue.",
              details: null,
            },
            meta: { request_id: "r" },
          }),
          { status: 401, headers: { "Content-Type": "application/json" } },
        ),
    });
    const { result } = renderHook(() => ({ region: useRegion(), session: useSession() }), {
      wrapper,
    });
    await waitFor(() => expect(result.current.session.isAuthenticated).toBe(false));
    expect(result.current.session.endedReason).toBe("expired");
  });

  it("never sends a stale token with the login request", async () => {
    seedSession();
    const fetchMock = stubApi({
      "GET /regions": REGIONS,
      "POST /auth/login": {
        access_token: "fresh",
        token_type: "bearer",
        expires_at: new Date(Date.now() + 3_600_000).toISOString(),
        user: { id: "u1", username: "official", display_name: "Demo Official", role: "official" },
      },
    });
    const { result } = renderHook(() => useSession(), { wrapper });
    await act(() => result.current.signIn("official", "pw"));
    const login = fetchMock.mock.calls.find(([u]) => String(u).endsWith("/auth/login"))!;
    expect((login[1] as RequestInit).headers).not.toHaveProperty("Authorization");
  });
});
