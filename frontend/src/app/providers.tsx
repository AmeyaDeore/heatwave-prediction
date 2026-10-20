import { QueryClientProvider, type QueryClient } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { TooltipProvider } from "@/components/ui/tooltip";
import { RegionProvider } from "@/state/region";
import { SessionProvider } from "@/state/session";
import { ThemeProvider } from "@/state/theme";

/**
 * Global state, outermost first: theme → server cache → session → selected region. The
 * region provider sits inside the query client because it loads the region list through it.
 */
export function AppProviders({ client, children }: { client: QueryClient; children: ReactNode }) {
  return (
    <ThemeProvider>
      <QueryClientProvider client={client}>
        <SessionProvider>
          <RegionProvider>
            <TooltipProvider delayDuration={200}>{children}</TooltipProvider>
          </RegionProvider>
        </SessionProvider>
      </QueryClientProvider>
    </ThemeProvider>
  );
}
