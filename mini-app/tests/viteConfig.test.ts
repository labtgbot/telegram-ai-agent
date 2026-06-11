import { describe, expect, it } from "vitest";
import { loadConfigFromFile } from "vite";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const configPath = resolve(dirname(fileURLToPath(import.meta.url)), "../vite.config.ts");

describe("Vite production build config", () => {
  it("does not emit public source maps", async () => {
    const result = await loadConfigFromFile({ command: "build", mode: "production" }, configPath);

    expect(result?.config.build?.sourcemap).toBe(false);
  });
});
