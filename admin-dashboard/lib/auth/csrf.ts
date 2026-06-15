export const CSRF_COOKIE_NAME = "admin_csrf_token";
export const CSRF_HEADER_NAME = "x-csrf-token";

export function readCsrfTokenFromCookieString(cookieString: string): string | undefined {
  for (const cookie of cookieString.split(";")) {
    const [name, ...valueParts] = cookie.trim().split("=");
    if (name !== CSRF_COOKIE_NAME || valueParts.length === 0) continue;
    const value = valueParts.join("=");
    try {
      return decodeURIComponent(value);
    } catch {
      return value;
    }
  }
  return undefined;
}

export function csrfHeaders(cookieString?: string): HeadersInit {
  const source = cookieString ?? (typeof document === "undefined" ? "" : document.cookie);
  const token = readCsrfTokenFromCookieString(source);
  return token ? { [CSRF_HEADER_NAME]: token } : {};
}
