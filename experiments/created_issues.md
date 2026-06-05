
### Stage 0
- [ ] #138 — [SEC][CRITICAL] Admin dashboard signs/verifies JWTs with hardcoded fallback secret `change-me`
- [ ] #139 — [DATA][CRITICAL] `token_usage_logs` partition exhaustion — INSERTs fail ~2 months after deploy

### Stage 1
- [ ] #140 — [SEC][HIGH] Per-user rate limiting is bypassed — `request.state.user` is never set
- [ ] #141 — [SEC][HIGH] Telegram webhook signature verification disabled by default with no production guard
- [ ] #142 — [SEC][HIGH] Bot chat commands bypass rate limiting entirely
- [ ] #143 — [SEC][HIGH] `X-Forwarded-For` trusted unconditionally → rate-limit evasion + forged audit IPs
- [ ] #144 — [BUG][HIGH] Account-deletion worker: one failure rolls back the whole GDPR batch
- [ ] #145 — [BUG][HIGH] Stale balance cache after a successful Stars purchase (pending branch)
- [ ] #146 — [DATA][HIGH] Model/migration drift drops payment-idempotency & welcome-uniqueness in model-built schemas
- [ ] #147 — [BUG][HIGH] Mini App calls non-existent backend routes (profile / delete-account / data-export broken)
- [ ] #148 — [DEVOPS][HIGH] `compose.prod.yml` runs as root, no resource limits, Redis without auth, mutable `:latest` tags
- [ ] #149 — [DEVOPS][HIGH] `.trivyignore` waives 14 Next.js CVEs citing a mitigation (admin IP-allowlist) that isn't deployed

### Stage 2
- [ ] #150 — [SEC][MEDIUM] No brute-force throttle on admin login; attempt counter is resettable
- [ ] #151 — [SEC][MEDIUM] CSV/formula injection in admin user export
- [ ] #152 — [SEC][MEDIUM] Telegram initData accepted via URL query parameter (credential leaks to logs)
- [ ] #153 — [SEC][MEDIUM] Admin audit log readable by the least-privileged `analyst` role
- [ ] #154 — [BUG][MEDIUM] Concurrent daily-bonus claim raises 500 instead of AlreadyClaimed and poisons the session
- [ ] #155 — [BUG][MEDIUM] Write-through balance cache can serve uncommitted / rolled-back balances
- [ ] #156 — [BUG][MEDIUM] TOCTOU pre-check in AI generation services burns provider cost under concurrency
- [ ] #157 — [BUG][MEDIUM] Broadcast worker lacks row claiming → duplicate sends under overlapping runs
- [ ] #158 — [BUG][MEDIUM] No webhook `update_id` idempotency → double side effects on Telegram redelivery
- [ ] #159 — [BUG][MEDIUM] Broadcast 429 backoff is single-shot → drops recipients during sustained flood limit
- [ ] #160 — [SEC][MEDIUM] Admin dashboard open redirect via protocol-relative `from` parameter
- [ ] #161 — [SEC][MEDIUM] Admin middleware role map omits `/system` and `/content` (default to analyst)
- [ ] #162 — [BUG][MEDIUM] Admin auth verify/refresh persist tokens without validating the upstream payload
- [ ] #163 — [BUG][MEDIUM] Mini App swallows API errors (no auth vs diagnostic distinction)
- [ ] #164 — [BUG][MEDIUM] Mini App chat never refreshes the displayed balance after token spend
- [ ] #165 — [DATA][MEDIUM] Alembic autogenerate lacks a partition guard → may emit destructive drops
- [ ] #166 — [DEVOPS][MEDIUM] Secret-scan gaps: over-broad gitleaks allowlist + `npm audit --audit-level=critical`
- [ ] #167 — [DEVOPS][MEDIUM] Monitoring stack ships Grafana `admin/admin` and unauthenticated Prometheus/Alertmanager/Loki

### Stage 3
- [ ] #168 — [SEC][LOW] Auth hardening: non-constant-time webhook compare, TOTP replay window, admin enumeration
- [ ] #169 — [SEC][LOW] Admin middleware leaks `x-admin-role` / `x-admin-sub` response headers
- [ ] #170 — [DATA][LOW] Redundant indexes on `users.telegram_id`/`referral_code`; `usage_log_id` has no FK
- [ ] #171 — [FRONT][LOW] Mini App retries 4xx requests and ships source maps to production
- [ ] #172 — [DEVOPS][LOW] CI supply-chain: third-party actions pinned to mutable tags; kubeval `continue-on-error`