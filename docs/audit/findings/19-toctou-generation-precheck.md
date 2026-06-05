## Summary

Flat-rate generation services check the balance with an unlocked cache-first read, then run the paid provider call, then debit with a locked `spend`; concurrent requests all pass the pre-check and incur real provider cost before the surplus debits fail.

| | |
|---|---|
| **Severity** | MEDIUM |
| **Confidence** | MEDIUM |
| **Area** | backend |
| **Remediation stage** | Stage 2 — Medium priority (correctness / hardening) |
| **Estimated complexity** | Medium |

## Evidence

Identical pattern in `web_search.py:153→185`, `image_generation.py`, `text_generation.py`, `voice_processing.py`, `document_analysis.py`: `_assert_balance_sufficient` (unlocked `get_balance`) → provider call → `spend` (locked, refuses negative). Voice is worst (two provider calls for a flat 5-token charge).

## Impact

No negative balance and no free tokens to the user, but a user firing N parallel requests with balance for fewer than N forces several paid provider calls that then fail to debit — burnable upstream cost.

## Suggested fix

Align flat-rate services with the video service's debit-first model (spend before invoking the provider, refund on provider failure), or treat `InsufficientTokensError` from `spend` as the only gate and drop reliance on the advisory pre-check.

## Acceptance criteria

- [ ] Provider calls are not executed for requests that cannot be charged.
- [ ] A concurrency test confirms surplus parallel requests do not trigger provider calls.

---
_Filed as part of the full-logic audit requested in #136. See `docs/audit/README.md` for the complete report._
