# Closed Beta Program

The closed beta runs against the **production** Telegram bot for 7–10
days before the public announcement. Goal: surface integration issues
and pricing friction with a representative cohort, on real
infrastructure, without paying for marketing reach we cannot absorb.

This document is the operator runbook. Acceptance criteria mapped from
[issue #37](https://github.com/labtgbot/telegram-ai-agent/issues/37):

> Beta: 50–100 приглашённых пользователей, обратная связь собрана и
> обработана.

## 1. Cohort

* **Target size:** 50–100 active users. We invite ~150 so attrition
  (people who accept but never `/start` the bot) does not push us
  below 50.
* **Profile mix (recommended):**
  - 60 % Russian-speaking Telegram power users (the home market).
  - 25 % English-speaking users sourced from AI/automation
    communities.
  - 10 % paying customers of competitor bots (`@chaton_bot`,
    `@mira_app_bot`) recruited through public channels.
  - 5 % friends & family (smoke testers for fresh-install flow on
    iOS, Android, Telegram Desktop, macOS, Web).
* **Selection:** prefer users with prior Telegram Stars transactions —
  the launch revenue gate depends on a Stars purchase landing on the
  production bot during the beta.

## 2. Invite mechanics

Beta gating lives in three places that are already in production:

| Mechanism | Where | Behaviour |
| --- | --- | --- |
| Referral code | `users.referral_code` | Each invite link is unique and traces back to the inviter. |
| Signup bonus | `TELEGRAM_SIGNUP_BONUS_TOKENS=50` | Default credit on first `/start`. We raise to **200** for the beta cohort (see step 3). |
| Allow-list | `admin_settings.beta_only_mode` (planned) | Blocks new users without an invite. Disabled by default at launch — flip on only if abuse spikes. |

Workflow:

1. Operator generates an invite URL with the canonical referrer
   account (the project's admin Telegram id):
   ```
   https://t.me/<bot_username>?start=ref-<admin_user_id>
   ```
2. Operator drops the link into the recruitment channels (1:1 DMs,
   targeted community posts). **No public posting** until the
   marketing announcement — the cohort cap is intentional.
3. The bot's existing referral logic credits the bonus on the
   invitee's first purchase (`docs/TOKEN_ECONOMY.md`).

### Beta signup bonus

To compensate beta testers for finding issues, run the following
admin SQL once (or use the admin CRM "Bonus → Bulk credit" tool when
it lands):

```sql
UPDATE admin_settings
SET value = '200', updated_at = now()
WHERE key = 'signup_bonus_tokens';
```

Revert to 50 after the beta window closes:

```sql
UPDATE admin_settings
SET value = '50', updated_at = now()
WHERE key = 'signup_bonus_tokens';
```

The same setting drives the prod default for the public launch — no
code change needed.

## 3. Communications cadence

| Day | Action | Channel |
| --- | --- | --- |
| -2  | "You're in" DM with invite link + what to expect. | Telegram DM from the project admin account. |
| 0   | Beta opens. Pinned message in the cohort group with the feedback survey. | Private Telegram group `@tgai_beta_lounge`. |
| 3   | Pulse check: anonymous poll on top friction. | Same group, Telegram poll. |
| 7   | Feedback survey closes. | Survey link. |
| 8–10| Triage + acknowledgement DMs to every respondent. | Telegram DM. |
| 10  | Beta closes, public-launch goal restated. | Pinned message. |

## 4. Feedback collection

### 4.1 Survey

We use a single Telegram WebApp-friendly survey hosted on a static
form runner (Tally / Google Forms) — no extra backend surface. The
survey link is shared in the cohort group and is also returned by the
bot's `/feedback` deep link (`https://t.me/<bot>?start=feedback`).

Survey schema (versioned with the launch — keep this file in sync with
the form):

```yaml
- id: nps
  type: int
  min: 0
  max: 10
  question: "How likely are you to recommend the bot to a friend?"
- id: most_useful
  type: choice
  options: [image, video, text, voice, web_search, documents]
  multiple: true
  question: "Which features did you use the most?"
- id: purchase_attempted
  type: bool
  question: "Did you try to buy tokens with Telegram Stars?"
- id: purchase_blockers
  type: text
  show_if: { purchase_attempted: false }
  question: "Why didn't you complete a purchase?"
- id: pricing_fair
  type: choice
  options: [too_low, fair, too_high]
  question: "Is the pricing in the catalog reasonable?"
- id: top_issue
  type: text
  question: "Biggest problem you ran into during the beta."
- id: nice_to_have
  type: text
  question: "One feature you wish existed."
- id: contact_ok
  type: bool
  question: "May we DM you with follow-up questions?"
```

### 4.2 In-app signals

The survey complements telemetry that's already shipping:

* `events_total{event="bot_start"}` — invite-to-activation funnel.
* `payment_events_total{event="successful_payment"}` — beta revenue.
* `tokens_spent_total{service=…}` — feature mix per cohort.
* Sentry releases tagged `beta` — bug surface area without scraping
  feedback text.
* `account_deletion_requested_total` — bail-out rate after the cohort
  signs up.

Build a Grafana dashboard at `deploy/monitoring/grafana/dashboards/
beta.json` filtering all metrics by the beta cohort (`user.cohort =
"beta"` — set on first `/start` from a beta referral code) so the
business + on-call rotations watch the same set of charts.

## 5. Triage

All survey responses are dumped into a triage spreadsheet (one row per
respondent) and classified within 24 h:

| Bucket | Action | Owner |
| --- | --- | --- |
| `P0 / blocker` | Hotfix during the beta window. File a `priority/p0` issue, link it from the launch checklist. | On-call engineer. |
| `P1 / launch-blocker` | Must ship before public announcement. | Project lead. |
| `P2 / fast-follow` | Ship in the next minor release after launch. | Triaged into milestone "1.1". |
| `nice-to-have` | Backlog. | Triaged into milestone "future". |
| `pricing` | Routed to the pricing review in `docs/PRICING_STRATEGY.md`. | Project lead. |
| `out-of-scope` | Acknowledge politely; close the loop. | Beta coordinator. |

A weekly summary is committed to `docs/BETA_REPORT.md` (template lives
under `docs/templates/BETA_REPORT.template.md`) so the public release
notes can cite the work that addressed user feedback.

## 6. Exit criteria

The beta is considered "obratная связь обработана" when **all** of the
following are true:

- [ ] ≥ 50 unique users completed `/start` and triggered at least one
      AI service call.
- [ ] ≥ 5 distinct Stars purchases landed on the production bot (the
      idempotency, refund and renewal codepaths all see real traffic).
- [ ] Survey response rate ≥ 40 % of the activated cohort.
- [ ] Every P0 / P1 issue from §5 is closed.
- [ ] `docs/BETA_REPORT.md` is published and linked from
      `docs/CHANGELOG.md` v1.0.0.

If any item slips, push the public announcement by a week — the
launch checklist depends on these being green.

## 7. Privacy

Beta participants are treated like any other production user:

* Data minimisation rules from `docs/security/pii-minimization.md`
  apply.
* Survey storage uses pseudonymous ids (referral code, not Telegram
  username) so a future export request can identify only the data
  the user explicitly opted in to.
* Participants can leave the beta cohort group at any time without
  losing their account or balance.
