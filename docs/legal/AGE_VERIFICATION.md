# Age Verification Policy

The public Telegram AI Agent bot serves general-purpose AI tools and is
**not directed at children**. Most features are appropriate for users 16+
(Telegram's own minimum age in most jurisdictions; the GDPR digital
consent age varies between 13 and 16 across the EU).

When we expose features that require an explicit **18+** confirmation —
e.g. unrestricted text generation prompts, NSFW image moderation toggles —
the workflow below applies.

## Policy

1. Age-restricted features stay disabled until the user passes the
   verification flow described in Section 3.
2. We follow **data minimisation** — we never store identity documents.
   Only a derived `age_verified_at` boolean / timestamp is persisted.
3. Verification can be withdrawn by the user via Settings; doing so
   re-locks the feature.
4. Failure cases (verification declined, mismatch) do not block the rest
   of the Service.

## Implementation status

Phase 4 (current) ships the **policy + endpoint stub**:

- `GET /api/v1/user/me/age-verification` — returns the current state.
- `POST /api/v1/user/me/age-verification` — feature-flag gated stub. In
  development it accepts a `confirmed_18_plus: true` self-declaration; in
  production this route is **disabled** until a verified provider is
  wired up (e.g. Telegram Passport, Veriff, Yoti).

The endpoint is enabled by setting the env var
`COMPLIANCE_AGE_GATE_ENABLED=true` and only operates in environments
where `COMPLIANCE_AGE_GATE_PROVIDER` is one of: `self_declared` (dev only),
`telegram_passport`, `veriff`, `yoti`.

A production-grade provider integration is **out of scope for this
issue** and will be added in a follow-up when a 18+ feature actually
ships.

## Data flows when enabled

1. The Mini App calls `POST /user/me/age-verification` with the proof
   produced by the chosen provider (e.g. a signed Telegram Passport
   payload or a verification job ID from Veriff).
2. The backend validates the proof, stores `age_verified_at` and the
   provider name (no document is stored).
3. Subsequent calls to 18+ features check this flag.

## Audit & retention

- Audit log entry on every state change (verified / revoked).
- `age_verified_at` is cleared on account deletion (see
  [`PRIVACY_POLICY.md`](PRIVACY_POLICY.md) §7).
- The audit log is retained for 12 months.

## See also

- [`PRIVACY_POLICY.md`](PRIVACY_POLICY.md) — overall privacy posture.
- [`TERMS_OF_SERVICE.md`](TERMS_OF_SERVICE.md) §7 — Terms-of-Service
  reference to age-restricted features.
- [`backend/app/api/v1/compliance.py`](../../backend/app/api/v1/compliance.py)
  — endpoint stub.
