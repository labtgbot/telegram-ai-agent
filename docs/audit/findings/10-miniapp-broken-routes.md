## Summary

Three Mini App API calls target paths/methods that do not exist on the backend, so profile refresh silently fails and the two GDPR-critical actions are completely non-functional while appearing to work.

| | |
|---|---|
| **Severity** | HIGH |
| **Confidence** | HIGH |
| **Area** | mini-app |
| **Remediation stage** | Stage 1 — High priority (security / data-integrity) |
| **Estimated complexity** | Low |

## Evidence

`mini-app/src/services/userApi.ts`: `get("/users/me")` (:24), `post("/user/data-export")` (:38), `delete("/user/account")` (:42). The backend `user` router exposes `GET /user/me/export` (`user.py:479-480`), `DELETE /user/me` (`user.py:518-519`) and there is no `/users/me` profile route. `ProfilePage.tsx:42-43` swallows the 404 silently.

## Impact

`getProfile()` 404s on every ProfilePage mount (silent). "Delete account" and "Request data export" always fail (404/405) — two GDPR-critical actions are broken while looking functional.

## Suggested fix

Point the client at `GET /user/me` (or the correct profile route), `DELETE /user/me`, and `GET /user/me/export`; align HTTP methods. Add tests asserting exact path + method.

## Acceptance criteria

- [ ] Profile, delete-account and data-export call the real backend routes with correct methods.
- [ ] Delete-account and data-export succeed end-to-end.
- [ ] Tests assert the exact path + method for each call.

---
_Filed as part of the full-logic audit requested in #136. See `docs/audit/README.md` for the complete report._
