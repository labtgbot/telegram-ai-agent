#!/usr/bin/env node
/**
 * Dev helper: print a signed admin access token so you can poke the panel
 * without standing up the bot. Usage:
 *   node scripts/dev-token.mjs --sub 42 --role super_admin
 * Honours ADMIN_JWT_SECRET / ADMIN_JWT_ALGORITHM from the environment
 * (local/dev default: change-me / HS256). Never use this against a real secret.
 */
import { SignJWT } from "jose";

const DEFAULT_ADMIN_JWT_SECRET = "change-me";
const DEV_ENVIRONMENTS = new Set(["development", "dev", "local", "test", "ci"]);

const args = Object.fromEntries(
  process.argv.slice(2).reduce((acc, value, index, arr) => {
    if (value.startsWith("--") && index + 1 < arr.length)
      acc.push([value.slice(2), arr[index + 1]]);
    return acc;
  }, []),
);

const runtimeEnv = (process.env.NODE_ENV ?? "development").toLowerCase();
const configuredSecret = process.env.ADMIN_JWT_SECRET?.trim() ?? "";
const secret = configuredSecret || DEFAULT_ADMIN_JWT_SECRET;

if (!DEV_ENVIRONMENTS.has(runtimeEnv) && secret === DEFAULT_ADMIN_JWT_SECRET) {
  process.stderr.write(
    "Refusing to mint an admin token with the placeholder ADMIN_JWT_SECRET outside a dev environment. " +
      "Set NODE_ENV=development for local use or provide an explicit development ADMIN_JWT_SECRET.\n",
  );
  process.exit(1);
}

const sub = args.sub ?? "1";
const role = args.role ?? "super_admin";
const algorithm = process.env.ADMIN_JWT_ALGORITHM ?? "HS256";
const ttlSeconds = Number(args.ttl ?? 900);

const token = await new SignJWT({ sub, role, type: "access" })
  .setProtectedHeader({ alg: algorithm })
  .setIssuedAt()
  .setExpirationTime(`${ttlSeconds}s`)
  .setJti(crypto.randomUUID())
  .sign(new TextEncoder().encode(secret));

process.stdout.write(`${token}\n`);
