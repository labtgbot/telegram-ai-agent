/**
 * Public env vars — readable on both server and client.
 */
const DEFAULT_API_BASE_URL = "http://localhost:8000/api/v1";
const LOCAL_API_HOSTS = new Set(["localhost", "127.0.0.1", "0.0.0.0", "::1"]);

export class InsecureAdminApiBaseUrlError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "InsecureAdminApiBaseUrlError";
  }
}

function isLocalApiHostname(hostname: string): boolean {
  return LOCAL_API_HOSTS.has(hostname) || hostname.startsWith("127.");
}

function assertProductionApiBaseUrl(envName: string, value: string): void {
  if (process.env.NODE_ENV !== "production") return;

  let parsed: URL;
  try {
    parsed = new URL(value);
  } catch {
    throw new InsecureAdminApiBaseUrlError(
      `${envName} must be an absolute http(s) URL in production.`,
    );
  }

  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
    throw new InsecureAdminApiBaseUrlError(`${envName} must use http or https in production.`);
  }

  if (isLocalApiHostname(parsed.hostname)) {
    throw new InsecureAdminApiBaseUrlError(
      `Refusing to start admin dashboard with local ${envName}=${value}. ` +
        `Set ${envName} to a non-localhost production API URL.`,
    );
  }
}

function resolvePublicApiBaseUrl(): string {
  const value = process.env.NEXT_PUBLIC_API_BASE_URL ?? DEFAULT_API_BASE_URL;
  assertProductionApiBaseUrl("NEXT_PUBLIC_API_BASE_URL", value);
  return value;
}

export const publicEnv = {
  get apiBaseUrl() {
    return resolvePublicApiBaseUrl();
  },
} as const;

const DEFAULT_ADMIN_JWT_SECRET = "change-me";
const MIN_PRODUCTION_JWT_SECRET_LENGTH = 32;

export class InsecureAdminJwtSecretError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "InsecureAdminJwtSecretError";
  }
}

function resolveAdminJwtSecret(): string {
  const configured = process.env.ADMIN_JWT_SECRET;
  const normalized = configured?.trim() ?? "";

  if (process.env.NODE_ENV === "production") {
    if (!normalized || normalized === DEFAULT_ADMIN_JWT_SECRET) {
      throw new InsecureAdminJwtSecretError(
        "Refusing to start admin dashboard with insecure ADMIN_JWT_SECRET. " +
          "Set ADMIN_JWT_SECRET to a high-entropy production secret.",
      );
    }
    if (normalized.length < MIN_PRODUCTION_JWT_SECRET_LENGTH) {
      throw new InsecureAdminJwtSecretError(
        `ADMIN_JWT_SECRET must be at least ${MIN_PRODUCTION_JWT_SECRET_LENGTH} characters in production.`,
      );
    }
  }

  return normalized ? configured! : DEFAULT_ADMIN_JWT_SECRET;
}

/**
 * Server-only env vars. Importing this module from a client component will
 * fail the Next.js build because of the secret access below.
 */
export function serverEnv() {
  const apiBaseUrl = process.env.API_BASE_URL ?? publicEnv.apiBaseUrl;
  assertProductionApiBaseUrl("API_BASE_URL", apiBaseUrl);

  return {
    apiBaseUrl,
    jwtSecret: resolveAdminJwtSecret(),
    jwtAlgorithm: process.env.ADMIN_JWT_ALGORITHM ?? "HS256",
  } as const;
}
