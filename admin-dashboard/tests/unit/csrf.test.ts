import { describe, expect, it } from "vitest";

import { CSRF_HEADER_NAME, csrfHeaders, readCsrfTokenFromCookieString } from "@/lib/auth/csrf";

describe("CSRF helpers", () => {
  it("reads the admin CSRF token from a cookie string", () => {
    expect(
      readCsrfTokenFromCookieString("theme=dark; admin_csrf_token=token-123; other=value"),
    ).toBe("token-123");
  });

  it("decodes cookie encoded CSRF token values", () => {
    expect(readCsrfTokenFromCookieString("admin_csrf_token=token%2Fwith%2Bchars")).toBe(
      "token/with+chars",
    );
  });

  it("keeps malformed percent-encoded cookie values readable", () => {
    expect(readCsrfTokenFromCookieString("admin_csrf_token=token%zz")).toBe("token%zz");
  });

  it("builds the CSRF header only when the cookie is present", () => {
    expect(csrfHeaders("admin_csrf_token=token-123")).toEqual({
      [CSRF_HEADER_NAME]: "token-123",
    });
    expect(csrfHeaders("theme=dark")).toEqual({});
  });
});
