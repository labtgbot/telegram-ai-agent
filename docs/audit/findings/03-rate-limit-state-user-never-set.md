## Summary

Every authenticated request is rate-limited as an anonymous IP bucket because the Telegram init-data auth dependency never writes `request.state.user`, which the limiter (and the active-user metric) rely on.

| | |
|---|---|
| **Severity** | HIGH |
| **Confidence** | HIGH |
| **Area** | backend |
| **Remediation stage** | Stage 1 — High priority (security / data-integrity) |
| **Estimated complexity** | Low |

## Evidence

`backend/app/api/rate_limit.py:125-131`
```python
user = getattr(request.state, "user", None)
if user is not None:
    plan = await resolve_plan_for_user(session, user)
    identifier = str(user.telegram_id)
else:
    plan = PLAN_ANONYMOUS
    identifier = f"ip:{_client_ip(request)}"
```
`backend/app/auth/dependencies.py:108-159` (`get_current_user_from_init_data`) returns the user but never sets `request.state.user` / `request.state.user_id`. A repo-wide grep confirms `request.state.user` is only ever *read*. The `anonymous` plan defines only `per_hour=5` and none of the per-media (`image_per_day`, `video_per_day`, …) buckets, and `RateLimitConfig.rules_for` silently skips undefined keys.

## Impact

All per-plan daily caps and all per-media caps are never enforced for real users — the expensive AI generation endpoints are effectively unthrottled (only a shared 5/hour anonymous bucket applies, itself bypassable — see finding on `X-Forwarded-For`). Paying users are wrongly throttled to the anonymous bucket shared per IP. The active-user metric (`metrics.py:273`, expects `request.state.user_id`) is also undercounted.

## Suggested fix

Set `request.state.user = user` (and `request.state.user_id = user.id`) inside `get_current_user_from_init_data` before returning, and ensure the auth dependency is resolved before the rate-limit dependency runs. Add a regression test asserting an authenticated generate request is bucketed under the user's plan.

## Acceptance criteria

- [ ] Authenticated generate requests are bucketed by the user's plan, not `anonymous`.
- [ ] Per-plan and per-media daily caps are enforced for authenticated users.
- [ ] Active-user metric increments for authenticated requests.
- [ ] Regression test covers plan resolution for an authenticated caller.

---
_Filed as part of the full-logic audit requested in #136. See `docs/audit/README.md` for the complete report._
