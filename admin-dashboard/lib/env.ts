/**
 * Public env vars — readable on both server and client.
 */
export const publicEnv = {
  apiBaseUrl: process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000/api/v1",
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
  return {
    apiBaseUrl: process.env.API_BASE_URL ?? publicEnv.apiBaseUrl,
    jwtSecret: resolveAdminJwtSecret(),
    jwtAlgorithm: process.env.ADMIN_JWT_ALGORITHM ?? "HS256",
  } as const;
}
