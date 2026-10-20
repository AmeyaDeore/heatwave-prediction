/// <reference types="vitest/config" />
import path from "node:path";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

const configDir = path.resolve(__dirname, "../config");

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
      // The shared label table (Part 06 §5) is imported from config/, never copied.
      "@config": configDir,
    },
  },
  server: {
    port: 5173,
    strictPort: true,
    fs: { allow: [__dirname, configDir] },
  },
  build: {
    rollupOptions: {
      output: {
        // Long-lived vendor chunks: a page change doesn't invalidate the framework in the cache.
        manualChunks(id) {
          if (!id.includes("node_modules")) return undefined;
          if (/[\\/]node_modules[\\/](react|react-dom|scheduler)[\\/]/.test(id)) return "react";
          if (id.includes("react-router")) return "router";
          if (id.includes("@tanstack")) return "query";
          if (id.includes("@radix-ui") || id.includes("radix-ui")) return "radix";
          if (id.includes("lucide-react")) return "icons";
          return "vendor";
        },
      },
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    css: false,
    restoreMocks: true,
  },
});
