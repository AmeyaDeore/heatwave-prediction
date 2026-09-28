// Baseline lint config. Part 10 extends it with framework plugins once the stack is chosen.
import js from "@eslint/js";
import prettier from "eslint-config-prettier";
import globals from "globals";

export default [
  { ignores: ["dist/", "node_modules/"] },
  js.configs.recommended,
  {
    languageOptions: {
      ecmaVersion: "latest",
      sourceType: "module",
      globals: { ...globals.browser },
    },
  },
  prettier,
];
