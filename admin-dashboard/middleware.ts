import { NextResponse, type NextRequest } from "next/server";

import { COOKIE_NAMES, verifyAdminAccessToken, TokenExpiredError } from "@/lib/auth/tokens";
import { roleSatisfies, type Role } from "@/lib/auth/roles";

const PUBLIC_PATHS = ["/login", "/api/auth/login/request", "/api/auth/login/verify"];

/**
 * Route → minimum required role. Missing entries default to `analyst`
 * for read-only dashboards; operational areas are listed explicitly.
 */
const ROUTE_ROLES: Array<{ prefix: string; required: Role }> = [
  { prefix: "/pricing", required: "super_admin" },
  { prefix: "/settings", required: "super_admin" },
  { prefix: "/system", required: "super_admin" },
  { prefix: "/broadcast", required: "support_admin" },
  { prefix: "/content", required: "support_admin" },
  { prefix: "/users", required: "support_admin" },
  { prefix: "/transactions", required: "support_admin" },
];

function isPublic(pathname: string): boolean {
  return PUBLIC_PATHS.some((p) => pathname === p || pathname.startsWith(`${p}/`));
}

function requiredRoleFor(pathname: string): Role {
  for (const entry of ROUTE_ROLES) {
    if (pathname === entry.prefix || pathname.startsWith(`${entry.prefix}/`)) {
      return entry.required;
    }
  }
  return "analyst";
}

function redirectToLogin(request: NextRequest, reason?: string): NextResponse {
  const url = new URL("/login", request.url);
  if (request.nextUrl.pathname !== "/") {
    url.searchParams.set("from", request.nextUrl.pathname);
  }
  if (reason) url.searchParams.set("reason", reason);
  const response = NextResponse.redirect(url);
  if (reason === "expired") {
    response.cookies.delete(COOKIE_NAMES.access);
  }
  return response;
}

export async function middleware(request: NextRequest): Promise<NextResponse> {
  const { pathname } = request.nextUrl;

  if (isPublic(pathname)) return NextResponse.next();

  const token = request.cookies.get(COOKIE_NAMES.access)?.value;
  if (!token) return redirectToLogin(request);

  try {
    const payload = await verifyAdminAccessToken(token);
    const required = requiredRoleFor(pathname);
    if (!roleSatisfies(payload.role, required)) {
      const url = new URL("/dashboard", request.url);
      url.searchParams.set("reason", "forbidden");
      return NextResponse.redirect(url);
    }
    return NextResponse.next();
  } catch (err) {
    if (err instanceof TokenExpiredError) {
      return redirectToLogin(request, "expired");
    }
    return redirectToLogin(request, "invalid");
  }
}

export const config = {
  matcher: [
    /*
     * Run on every request except static assets, the favicon, and Next.js
     * internals. Route handlers under /api stay covered so we can gate
     * server actions too.
     */
    "/((?!_next/static|_next/image|favicon.ico|robots.txt|.*\\.(?:png|jpg|jpeg|gif|svg|webp|ico)$).*)",
  ],
};
