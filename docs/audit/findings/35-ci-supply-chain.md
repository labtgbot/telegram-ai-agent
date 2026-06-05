## Summary

Workflows pin third-party actions to mutable major-version tags (and `instrumenta/kubeval-action@master`), and the only K8s-manifest validation step is `continue-on-error`, so it is effectively decorative.

| | |
|---|---|
| **Severity** | LOW |
| **Confidence** | HIGH |
| **Area** | devops |
| **Remediation stage** | Stage 3 — Low priority (hygiene / defence-in-depth) |
| **Estimated complexity** | Low |

## Evidence

`.github/workflows/*.yml` reference `@v6`/`@v2`/`@v0.36.0` and `instrumenta/kubeval-action@master` (`ci.yml:125`); privileged jobs run with `packages: write`/`security-events: write`/`contents: write`. `ci.yml:124-128` sets `continue-on-error: true` on the kubeval step.

## Impact

A compromised/retagged action (especially the unpinned `@master` from an unmaintained third party) executes in CI with write scopes; invalid manifests never fail CI and can reach `helm upgrade`.

## Suggested fix

Pin third-party actions to a full commit SHA (especially `kubeval-action`); switch to a maintained, pinned validator (kubeconform) and remove `continue-on-error`.

## Acceptance criteria

- [ ] Third-party actions are SHA-pinned.
- [ ] Manifest validation fails CI on invalid manifests.

---
_Filed as part of the full-logic audit requested in #136. See `docs/audit/README.md` for the complete report._
