import { describe, expect, it } from "vitest";

import eslintConfig from "../../eslint.config.mjs";

describe("eslint config", () => {
  it("keeps Next.js linting without ESLint 10 incompatible react plugin rules", () => {
    const appConfig = eslintConfig.find((config) =>
      config.files?.includes("**/*.{js,jsx,ts,tsx}"),
    );

    expect(appConfig).toBeDefined();
    expect(appConfig?.rules).toBeDefined();
    expect(appConfig?.plugins).not.toHaveProperty("react");
    expect(Object.keys(appConfig?.rules ?? {})).not.toContain("react/display-name");
    expect(Object.keys(appConfig?.rules ?? {})).toContain("@next/next/no-html-link-for-pages");
    expect(Object.keys(appConfig?.rules ?? {})).toContain("react-hooks/rules-of-hooks");
  });
});
