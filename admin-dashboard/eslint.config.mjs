import nextVitals from "eslint-config-next/core-web-vitals";
import prettier from "eslint-config-prettier/flat";
import globals from "globals";

const nextConfigs = nextVitals.map((config) => {
  if (config.name === "next") {
    return {
      ...config,
      files: ["**/*.{js,jsx,ts,tsx}"],
    };
  }

  if (config.name === "next/typescript") {
    return config;
  }

  return config;
});

export default [
  ...nextConfigs,
  {
    languageOptions: {
      globals: {
        ...globals.browser,
        ...globals.node,
      },
    },
  },
  {
    files: ["**/*.{ts,tsx}"],
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
  },
  prettier,
];
