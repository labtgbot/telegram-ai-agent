// @vitest-environment node
import { execFile } from "node:child_process";
import { promisify } from "node:util";

import { describe, expect, it } from "vitest";

const execFileAsync = promisify(execFile);

describe("scripts/dev-token.mjs", () => {
  it("refuses to mint a token with the placeholder secret outside dev environments", async () => {
    await expect(
      execFileAsync(process.execPath, ["scripts/dev-token.mjs"], {
        cwd: process.cwd(),
        env: {
          ...process.env,
          ADMIN_JWT_SECRET: "",
          NODE_ENV: "production",
        },
      }),
    ).rejects.toMatchObject({
      code: 1,
      stderr: expect.stringContaining("ADMIN_JWT_SECRET"),
    });
  });
});
