// Lint config for the React + TypeScript frontend (Part 10).
import js from "@eslint/js";
import prettier from "eslint-config-prettier";
import reactHooks from "eslint-plugin-react-hooks";
import reactRefresh from "eslint-plugin-react-refresh";
import globals from "globals";
import tseslint from "typescript-eslint";

export default tseslint.config(
  { ignores: ["dist/", "coverage/", "node_modules/"] },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: ["**/*.{ts,tsx}"],
    languageOptions: {
      ecmaVersion: "latest",
      sourceType: "module",
      globals: { ...globals.browser },
    },
    plugins: { "react-hooks": reactHooks, "react-refresh": reactRefresh },
    rules: {
      ...reactHooks.configs.recommended.rules,
      "react-refresh/only-export-components": ["warn", { allowConstantExport: true }],
      "@typescript-eslint/no-unused-vars": ["error", { argsIgnorePattern: "^_" }],
    },
  },
  {
    // Design rule (Part 10 §4.1): pages and shared components never use raw Tailwind palette
    // colours; they go through the semantic tokens (bg-risk-*, bg-tone-*, text-muted-foreground …).
    files: [
      "src/pages/**/*.tsx",
      "src/components/shared/**/*.tsx",
      "src/components/layout/**/*.tsx",
    ],
    rules: {
      "no-restricted-syntax": [
        "error",
        {
          selector:
            "Literal[value=/\\b(bg|text|border|from|to|via|ring|fill|stroke)-(red|orange|amber|yellow|lime|green|emerald|teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose|slate|gray|zinc|neutral|stone|white|black)(-\\d{2,3})?\\b/]",
          message:
            "Use a semantic design token (src/styles/globals.css) instead of a raw palette colour.",
        },
        {
          selector:
            "TemplateElement[value.raw=/\\b(bg|text|border|from|to|via|ring|fill|stroke)-(red|orange|amber|yellow|lime|green|emerald|teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose|slate|gray|zinc|neutral|stone|white|black)(-\\d{2,3})?\\b/]",
          message:
            "Use a semantic design token (src/styles/globals.css) instead of a raw palette colour.",
        },
      ],
    },
  },
  {
    // shadcn/ui primitives are generated; keep them close to upstream.
    files: ["src/components/ui/**/*.tsx"],
    rules: { "react-refresh/only-export-components": "off" },
  },
  {
    files: ["*.config.{js,ts}"],
    languageOptions: { globals: { ...globals.node } },
  },
  prettier,
);
