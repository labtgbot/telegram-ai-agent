/* eslint-env node */
module.exports = {
  root: true,
  extends: ["next/core-web-vitals", "next/typescript", "prettier"],
  ignorePatterns: [
    ".next",
    "node_modules",
    "coverage",
    "playwright-report",
    "test-results",
  ],
  rules: {
    "@typescript-eslint/consistent-type-imports": [
      "error",
      { prefer: "type-imports", fixStyle: "separate-type-imports" },
    ],
    "@typescript-eslint/no-unused-vars": [
      "error",
      { argsIgnorePattern: "^_", varsIgnorePattern: "^_" },
    ],
  },
};
