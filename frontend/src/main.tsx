import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { RouterProvider } from "react-router/dom";
import { AppProviders } from "@/app/providers";
import { createRouter } from "@/app/router";
import { createQueryClient } from "@/lib/query/client";
import "@/styles/globals.css";

const root = document.getElementById("root");
if (!root) throw new Error("index.html is missing #root.");

const queryClient = createQueryClient();
const router = createRouter();

createRoot(root).render(
  <StrictMode>
    <AppProviders client={queryClient}>
      <RouterProvider router={router} />
    </AppProviders>
  </StrictMode>,
);
