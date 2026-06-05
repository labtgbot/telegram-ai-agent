## Summary

The documented production-fallback docker-compose stack runs every container as root with no hardening or resource limits, exposes an unauthenticated Redis on the shared network, and defaults images to mutable `:latest` tags.

| | |
|---|---|
| **Severity** | HIGH |
| **Confidence** | HIGH |
| **Area** | devops |
| **Remediation stage** | Stage 1 — High priority (security / data-integrity) |
| **Estimated complexity** | Medium |

## Evidence

`docker/compose.prod.yml:18-123` — no `user:`, `read_only:`, `cap_drop:`, `security_opt: [no-new-privileges:true]` or `deploy.resources.limits` on any service (contrast the hardened Helm chart `backend-deployment.yaml:33-86`). Redis (`compose.prod.yml:112-123`) runs without `--requirepass`. Images default to `...:latest` (`:39,71,81`). Healthchecks use `wget` against images that may not bundle it (`:74-78,89-93`).

## Impact

A compromise of any container runs as root with full capabilities and no memory cap (one service can OOM the host; breakout is easier). Any container reaching Redis gets unauthenticated read/write to session/cache/rate-limit data. `:latest` makes deploys non-reproducible.

## Suggested fix

Add `user`, `read_only: true` (+ tmpfs), `cap_drop: [ALL]`, `security_opt: [no-new-privileges:true]` and `deploy.resources.limits` to each service (mirror Helm); set `--requirepass ${REDIS_PASSWORD:?}` and include it in `REDIS_URL`; pin image refs to a version/digest (or make them required); use a base-image-guaranteed healthcheck with a `start_period`.

## Acceptance criteria

- [ ] All compose.prod services run non-root with dropped capabilities and resource limits.
- [ ] Redis requires a password and `REDIS_URL` carries it.
- [ ] Image tags are pinned (not `:latest`).
- [ ] Healthchecks use a command guaranteed by the base image.

---
_Filed as part of the full-logic audit requested in #136. See `docs/audit/README.md` for the complete report._
