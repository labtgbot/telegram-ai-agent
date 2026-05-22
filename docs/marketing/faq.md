# Launch FAQ

Anticipated questions for the public announcement. Keep answers
short — link to the canonical doc instead of re-explaining.

## Pricing

**Q: Why is it cheaper than Mira / ChatOn?**
We bundle model inference on a single Composio account and run the
backend on commodity infrastructure. The token-to-Stars rate is
documented in [`docs/PRICING_STRATEGY.md`](../PRICING_STRATEGY.md);
the discount is roughly 50 % across the catalog.

**Q: Will the prices stay at this level?**
Catalog stays for v1.0.0. Admin-overridable pricing lands in a later
release (see `docs/PRICING_STRATEGY.md` §"Dynamic pricing").

**Q: Refunds?**
Stars purchases are refundable through Telegram support for 21 days.
We mirror the refund into the token ledger via the
`PaymentService.refund` codepath ([`docs/PAYMENTS.md`](../PAYMENTS.md)
§"Refunds").

## Privacy

**Q: Do you keep my prompts?**
We store conversation history in PostgreSQL so `/agent` can keep
context; you can wipe it any time from the Mini App
("Settings → Erase chat history"). Full policy:
[`docs/legal/PRIVACY_POLICY.md`](../legal/PRIVACY_POLICY.md).

**Q: GDPR export / deletion?**
Yes — the Mini App exposes "Export my data" and "Delete account".
Both routes are implemented in
`backend/app/api/v1/compliance.py` and acknowledged within 30 days.

## Reliability

**Q: What happens during a Telegram outage?**
Bot replies pause. We keep the Mini App reachable so users can check
their balance and queue work for later. Status updates land in our
public Telegram channel (linked from the bot's `/help`).

**Q: Are there SLOs?**
Yes — read p95 < 500 ms, write p95 < 2 s, 99.9 % monthly
availability. Full breakdown in
[`docs/PERFORMANCE.md`](../PERFORMANCE.md).

## Source code

**Q: Is this open source?**
Source-available. The license keeps commercial reuse with us, but
all docs and code are public for security review and learning.

**Q: How do I report a bug?**
`/feedback` inside the bot, or open an issue at
<https://github.com/labtgbot/telegram-ai-agent/issues>.
