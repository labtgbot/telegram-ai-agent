# Launch Checklist — v1.0.0

Operational checklist for taking the Telegram AI Agent from a tagged
release to publicly available bot. Owned by the on-call rotation. Each
item is a hard gate: if a check fails, abort the launch and roll back
per [`docs/DEPLOYMENT.md`](DEPLOYMENT.md) §11.

The acceptance criteria for [issue #37](https://github.com/labtgbot/telegram-ai-agent/issues/37)
map 1-to-1 against the sections below.

---

## 1. BotFather configuration

Configure the production bot's public identity from code instead of
typing values into BotFather by hand — the script is idempotent and
captures the canonical description, command list, menu button (Mini
App entry) and short description in version control.

```bash
TELEGRAM_BOT_TOKEN=$(op read 'op://prod/telegram-bot-token/password') \
TELEGRAM_BOT_USERNAME=telegram_ai_agent_bot \
TELEGRAM_MINI_APP_URL=https://app.telegram-ai-agent.example.com \
  python -m scripts.configure_botfather
```

`TELEGRAM_BOT_USERNAME` is sanity-checked against `getMe`, so the script
refuses to update the staging bot if the production token is misrouted.

Dry-run first against the production token to print the calls that
would be made:

```bash
TELEGRAM_BOTFATHER_DRY_RUN=1 \
TELEGRAM_BOT_TOKEN=... TELEGRAM_MINI_APP_URL=... \
  python -m scripts.configure_botfather
```

What the script applies (see `scripts/configure_botfather.py`):

| Endpoint | Purpose |
| --- | --- |
| `setMyCommands` | The same `BOT_COMMANDS` tuple used by the live `/help` text — guarantees the menu and the help reply never drift. |
| `setMyDescription` | Long description shown in the "What can this bot do?" card. |
| `setMyShortDescription` | One-line tagline shown in chat list previews and shared bot links. |
| `setChatMenuButton` | Replaces the default `/` menu with a "Открыть Mini App" web-app button pointing at `TELEGRAM_MINI_APP_URL`. |

The bot description and short description are applied for the default
locale plus `ru` and `en` so the catalog page matches the audience. To
narrow the localisation list, pass
`TELEGRAM_BOTFATHER_LANGUAGE_CODES=,ru`.

After the script finishes, verify in the Telegram client:

1. `@telegram_ai_agent_bot` profile → "What can this bot do?" matches
   `PRODUCTION_DESCRIPTION`.
2. The chat input panel shows the "Открыть Mini App" button (not the
   default `/` icon).
3. `/help` lists every command from `backend/app/bot/commands.py`.

---

## 2. Telegram Stars — production smoke test

Before announcing the bot we run an end-to-end Stars purchase against
the production deployment. The acceptance criterion is a single billed
transaction, captured in `transactions` with `status='completed'` and an
audit row in `token_usage_logs`.

Test runbook (see [`docs/PAYMENTS.md`](PAYMENTS.md) for the full flow):

1. Top up the test account with the minimum number of Stars required
   for the `starter` package (250 ⭐).
2. From the Mini App, open **Buy → Starter** and complete the invoice
   inside Telegram.
3. In Grafana → **Business** dashboard check that
   `payment_events_total{event="successful_payment"}` increments and
   `revenue_stars_total` advances by 250.
4. Run the SQL spot-check below from `psql`:

   ```sql
   SELECT id, user_id, package_code, stars_amount, tokens_amount,
          status, payment_id, completed_at
   FROM transactions
   WHERE user_id = :test_user_id
   ORDER BY completed_at DESC
   LIMIT 1;
   ```

   Expected: `status='completed'`, `payment_id` prefixed `tg:` (the
   stable Telegram-issued charge id), `tokens_amount=500`.
5. Replay the webhook with `curl` once to assert idempotency: the
   second `successful_payment` must not double-credit the balance.

If any step fails:

- check the dispatcher logs for `payments.duplicate_charge` or
  `payments.invoice_payload_invalid`;
- ensure `PAYMENT_PROVIDER_TOKEN` is **unset** (Stars uses the bot
  token, not a payment provider) and `PAYMENT_CURRENCY=XTR`.

Document the test transaction (Telegram `charge_id`, internal
transaction id, screenshot of the Stars receipt) in the release entry
in [`docs/CHANGELOG.md`](CHANGELOG.md) so audit has a paper trail.

---

## 3. Optional payment rails — TON / Stripe

Both rails are **optional for v1.0.0** and ship behind feature flags so
the launch can proceed with Stars only. See
[`docs/PAYMENTS_ALT.md`](PAYMENTS_ALT.md) for the integration steps when
they go live.

Set the flags explicitly in the production Helm values so the launch is
auditable:

```yaml
backend:
  env:
    PAYMENTS_TON_ENABLED: "false"
    PAYMENTS_STRIPE_ENABLED: "false"
```

---

## 4. Beta program — 50–100 invited users + feedback

The beta program runs against the **production** bot, with the cohort
gated by referral code. The acceptance criterion is a written
walkthrough of feedback collected and the resulting action items.

See [`docs/BETA_PROGRAM.md`](BETA_PROGRAM.md) for the invite flow,
feedback survey template and triage SLAs.

---

## 5. Production load test (100 concurrent users)

Run the `k6 production` smoke against the production hostname during a
maintenance window with the on-call rotation watching the SLO
dashboard. The scenario lives in
[`loadtest/production_100u.js`](../loadtest/production_100u.js) and
defends both read and write SLOs.

```bash
BASE_URL=https://api.telegram-ai-agent.example.com \
AUTH_TOKEN="$BETA_INIT_DATA" \
  k6 run loadtest/production_100u.js \
    --summary-export "loadtest/results/$(date +%Y%m%d)-launch-100u.json"
```

Exit gates:

- `http_req_duration{op:read} p95 < 500 ms`
- `http_req_duration{op:write} p95 < 2 s`
- `http_req_failed rate < 0.5 %`
- No `BackendUp` / `BackendErrorBudgetBurn` alerts fired

Archive the JSON summary under `loadtest/results/` and link it from the
release entry.

---

## 6. Marketing materials (optional)

Pre-launch comms live under [`docs/marketing/`](marketing/). Items are
optional for the technical launch but block the public announcement.

---

## 7. Release notes — `docs/CHANGELOG.md`

Update the **Unreleased** section in
[`docs/CHANGELOG.md`](CHANGELOG.md) with every notable change, then
promote it to a dated `v1.0.0` block when cutting the tag.

The `Release` workflow (`.github/workflows/release.yml`) extracts the
matching section into the GitHub Release body, so missing entries
silently drop notes from the release page.

---

## 8. Production deploy

Follow [`docs/PRODUCTION_DEPLOY.md`](PRODUCTION_DEPLOY.md). Highlights:

1. Tag the release: `git tag v1.0.0 && git push origin v1.0.0`. The
   tag triggers `Release`, which builds + pushes container images.
2. Promote the deploy: `helm upgrade telegram-ai-agent
   deploy/helm/telegram-ai-agent -n tgai-prod
   -f deploy/helm/telegram-ai-agent/values-production.yaml
   --set image.tag=1.0.0 --atomic --wait --timeout 10m`.
3. Run the post-deploy verification from §6 of
   [`docs/DEPLOYMENT.md`](DEPLOYMENT.md) (Alembic head, `/health`,
   `/metrics`).
4. Apply the BotFather configuration (§1 above).
5. Execute the Stars smoke test (§2).

If any step fails, abort and roll back with `helm rollback
telegram-ai-agent --wait`.

---

## 9. Post-launch monitoring

See [`docs/POST_LAUNCH.md`](POST_LAUNCH.md) for the first-72-hour watch
schedule, dashboards to babysit and the documented incident severities.
