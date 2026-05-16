/**
 * Public env vars — readable on both server and client.
 */
export const publicEnv = {
  apiBaseUrl: process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000/api/v1",
} as const;

/**
 * Server-only env vars. Importing this module from a client component will
 * fail the Next.js build because of the secret access below.
 */
export function serverEnv() {
  return {
    apiBaseUrl: process.env.API_BASE_URL ?? publicEnv.apiBaseUrl,
    jwtSecret: process.env.ADMIN_JWT_SECRET ?? "change-me",
    jwtAlgorithm: process.env.ADMIN_JWT_ALGORITHM ?? "HS256",
  } as const;
}
