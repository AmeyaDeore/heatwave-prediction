// Lint config for the Node.js + Express application API (Part 01 R2). Same base as frontend/.
import js from "@eslint/js";
import prettier from "eslint-config-prettier";
import globals from "globals";
import tseslint from "typescript-eslint";

export default tseslint.config(
  { ignores: ["dist/", "coverage/", "node_modules/"] },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: ["**/*.{ts,js}"],
    languageOptions: {
      ecmaVersion: "latest",
      sourceType: "module",
      globals: { ...globals.node },
    },
    rules: {
      "@typescript-eslint/no-unused-vars": ["error", { argsIgnorePattern: "^_" }],
      // Logs go through src/logger.ts (one JSON object per line), never bare console calls.
      "no-console": "error",
    },
  },
  {
    // The CLI prints results for a person to read; the logger is for the service.
    files: ["src/cli/**/*.ts"],
    rules: { "no-console": "off" },
  },
  prettier,
);
