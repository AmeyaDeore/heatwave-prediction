/**
 * Render a component, or a route, inside the real providers and shell.
 *
 * Revision 2: every page needs a session, so both helpers start signed in as a test official
 * unless given `{ signedIn: false }`.
 */
import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { createMemoryRouter, RouterProvider } from "react-router";
import { AppProviders } from "@/app/providers";
import { routes } from "@/app/router";
import { createQueryClient } from "@/lib/query/client";
import { STORAGE_KEYS } from "@/lib/storage";

export const TEST_SESSION = {
  token: "test-token",
  user: { id: "user_test", username: "official", display_name: "Demo Official", role: "official" },
};

/** Seed a signed-in session (as SessionProvider stores it) or clear it. */
export function seedSession(signedIn = true) {
  if (!signedIn) return sessionStorage.removeItem(STORAGE_KEYS.session);
  sessionStorage.setItem(
    STORAGE_KEYS.session,
    JSON.stringify({ ...TEST_SESSION, expiresAt: new Date(Date.now() + 3_600_000).toISOString() }),
  );
}

export function testQueryClient() {
  const client = createQueryClient();
  client.setDefaultOptions({
    queries: { ...client.getDefaultOptions().queries, retry: false },
    mutations: { retry: false },
  });
  return client;
}

export function renderWithProviders(
  ui: ReactElement,
  client = testQueryClient(),
  { signedIn = true } = {},
) {
  seedSession(signedIn);
  return { client, ...render(<AppProviders client={client}>{ui}</AppProviders>) };
}

export function renderRoute(path: string, client = testQueryClient(), { signedIn = true } = {}) {
  seedSession(signedIn);
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  return {
    client,
    router,
    ...render(
      <AppProviders client={client}>
        <RouterProvider router={router} />
      </AppProviders>,
    ),
  };
}
