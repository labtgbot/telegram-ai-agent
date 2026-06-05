## Summary

The optional monitoring compose stack uses default Grafana credentials and publishes Prometheus/Alertmanager/Loki on host ports with no auth.

| | |
|---|---|
| **Severity** | MEDIUM |
| **Confidence** | MEDIUM |
| **Area** | devops |
| **Remediation stage** | Stage 2 — Medium priority (correctness / hardening) |
| **Estimated complexity** | Low |

## Evidence

`deploy/monitoring/docker-compose.monitoring.yml:24-66` — `GF_SECURITY_ADMIN_USER/PASSWORD: admin` (`:45-46`) and host-published `9090/9093/3000/3100` with no auth proxy; Prometheus runs `--web.enable-lifecycle`.

## Impact

If ever run on a non-loopback host, Grafana is takeover-able with default creds and Prometheus/Alertmanager/Loki are fully open (config reload/shutdown, alert silencing, metrics/log exposure).

## Suggested fix

Parameterise the Grafana admin password (`${GF_SECURITY_ADMIN_PASSWORD:?}`), bind published ports to `127.0.0.1`, and document that this stack must not be exposed publicly.

## Acceptance criteria

- [ ] Grafana admin password is required via env (no `admin/admin` default).
- [ ] Monitoring ports bind to loopback by default.
- [ ] Docs warn against public exposure.

---
_Filed as part of the full-logic audit requested in #136. See `docs/audit/README.md` for the complete report._
