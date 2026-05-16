#!/usr/bin/env node
/**
 * Dev helper: print a signed admin access token so you can poke the panel
 * without standing up the bot. Usage:
 *   node scripts/dev-token.mjs --sub 42 --role super_admin
 * Honours ADMIN_JWT_SECRET / ADMIN_JWT_ALGORITHM from the environment
 * (defaults: change-me / HS256). Never use this against a real secret.
 */
import { SignJWT } from "jose";

const args = Object.fromEntries(
  process.argv.slice(2).reduce((acc, value, index, arr) => {
    if (value.startsWith("--") && index + 1 < arr.length) acc.push([value.slice(2), arr[index + 1]]);
    return acc;
  }, []),
);

const sub = args.sub ?? "1";
const role = args.role ?? "super_admin";
const secret = process.env.ADMIN_JWT_SECRET ?? "change-me";
const algorithm = process.env.ADMIN_JWT_ALGORITHM ?? "HS256";
const ttlSeconds = Number(args.ttl ?? 900);

const token = await new SignJWT({ sub, role, type: "access" })
  .setProtectedHeader({ alg: algorithm })
  .setIssuedAt()
  .setExpirationTime(`${ttlSeconds}s`)
  .setJti(crypto.randomUUID())
  .sign(new TextEncoder().encode(secret));

process.stdout.write(`${token}\n`);
