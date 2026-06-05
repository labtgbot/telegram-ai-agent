## Summary

The backend returns the authoritative `new_balance` on chat/image/search/video responses, but the chat page never calls `setBalance`, so the displayed balance stays stale.

| | |
|---|---|
| **Severity** | MEDIUM |
| **Confidence** | HIGH |
| **Area** | mini-app |
| **Remediation stage** | Stage 2 — Medium priority (correctness / hardening) |
| **Estimated complexity** | Low |

## Evidence

`mini-app/src/services/chatApi.ts:30-37` exposes `new_balance`; `ChatPage.tsx` imports `useUserStore` but reads only `user` (`:33`) and `onFinal` updates only the message bubble (`:148-153`) — `setBalance` is never called.

## Impact

After spending tokens the user sees a too-high balance until the next Balance-page refetch, over-estimating remaining requests (server remains authoritative, so no over-spend).

## Suggested fix

In `onFinal` (and the image/search/video success handlers) call `useUserStore.getState().setBalance(final.new_balance)` and/or invalidate the balance query.

## Acceptance criteria

- [ ] The displayed balance updates immediately after a chat token spend.
- [ ] Test asserts `setBalance` is called with `new_balance` on `onFinal`.

---
_Filed as part of the full-logic audit requested in #136. See `docs/audit/README.md` for the complete report._
