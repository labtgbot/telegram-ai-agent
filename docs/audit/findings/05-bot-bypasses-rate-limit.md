## Summary

AI generation triggered through the Telegram chat (`/ask`, `/agent`, `/image`, `/video`, free-text) calls the generation services directly without invoking the rate limiter, so the chat path has no hourly/daily/per-action quota at all.

| | |
|---|---|
| **Severity** | HIGH |
| **Confidence** | HIGH |
| **Area** | backend |
| **Remediation stage** | Stage 1 — High priority (security / data-integrity) |
| **Estimated complexity** | Medium |

## Evidence

Handlers `handle_image` (`backend/app/bot/handlers.py:321`), `handle_video` (`:483`) and `_run_text_mode` (`:643`) call the generation services but never call `RateLimiter.consume`. The webhook route (`backend/app/api/v1/bot.py:78-114`) has no `rate_limit` dependency and `dispatch_update` never invokes the limiter. The only consumer of `RateLimiter` is `backend/app/api/rate_limit.py`. The bot-side helper `backend/app/bot/rate_limit.py` (`format_rate_limit_message`, `upgrade_keyboard`) is dead code.

## Impact

A user driving generation through chat is subject to no quota — only token balance brakes them, and free signup/daily/referral bonuses make abuse of provider/Composio spend and Telegram send budget realistic. The Mini App path is protected; the chat path is not.

## Suggested fix

In `_run_text_mode`, `handle_image`, `handle_video`, resolve the user's plan and call `RateLimiter(...).consume(plan=..., identifier=str(telegram_id), action=...)` before invoking generation; on `RateLimitedError` reply using the existing `format_rate_limit_message` / `upgrade_keyboard` helpers.

## Acceptance criteria

- [ ] Bot image/video/text generation enforces the same per-plan quotas as the HTTP endpoints.
- [ ] A rate-limited chat request replies with the upgrade message instead of generating.
- [ ] Tests cover the chat rate-limit path for at least image and text.

---
_Filed as part of the full-logic audit requested in #136. See `docs/audit/README.md` for the complete report._
