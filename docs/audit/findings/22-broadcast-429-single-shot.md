## Summary

On a 429 the drain waits once and retries a single time; if the retry also returns 429 the recipient is permanently marked FAILED and the loop continues without honouring the second `retry_after`.

| | |
|---|---|
| **Severity** | MEDIUM |
| **Confidence** | HIGH |
| **Area** | backend |
| **Remediation stage** | Stage 2 — Medium priority (correctness / hardening) |
| **Estimated complexity** | Low |

## Evidence

`backend/app/services/broadcast.py:800-827` — single retry after a 429, then `record_recipient_result(delivered=result.delivered)`; no global pause.

## Impact

During sustained flood limiting legitimate recipients are dropped as failed and the worker keeps hammering the API at `interval`, prolonging the penalty.

## Suggested fix

Loop the backoff with bounded/exponential retries while `retry_after` is present; only mark FAILED after exhausting retries; consider pausing the whole drain on a 429.

## Acceptance criteria

- [ ] A recipient hit by repeated 429s is retried with backoff, not immediately failed.
- [ ] The drain pauses globally on a 429 rather than only the current recipient.
- [ ] Test simulates repeated 429s and asserts no premature FAILED.

---
_Filed as part of the full-logic audit requested in #136. See `docs/audit/README.md` for the complete report._
