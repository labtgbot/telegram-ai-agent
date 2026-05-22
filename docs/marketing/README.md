# Marketing Materials

> Optional. The technical launch (issue #37) can proceed without
> shipping any of the assets below — they unblock the **public**
> announcement that follows.

## Inventory

| File | Use |
| --- | --- |
| [`announcement-ru.md`](announcement-ru.md) | Russian launch post for Telegram channels + cross-posts. |
| [`announcement-en.md`](announcement-en.md) | English launch post for indie-maker forums (Product Hunt, IndieHackers, X). |
| [`one-liner.md`](one-liner.md) | 280-character tagline variants for ads, podcast intros, README badges. |
| [`press-kit/`](press-kit/) | Logo, screenshots, founder bio, contact email. (Bring your own — list checked into `press-kit/CHECKLIST.md`.) |
| [`faq.md`](faq.md) | Pre-empted questions for the launch threads. |

## Workflow

1. Two days before the public announcement: open a PR with the final
   copy. Review with the product lead.
2. Lock the timestamps the bot mentions (`@BotFather` username, Mini
   App URL) against the production config.
3. After the launch, archive engagement metrics (Telegram channel
   views, Product Hunt rank, X impressions) into
   `docs/marketing/results/YYYY-MM-DD-launch.md` so future launches
   can recalibrate.

## Quality bar

* Russian copy follows the tone of the existing bot replies — second
  person plural, no slang, no emoji spam (at most one ✨ per post).
* English copy avoids exaggerated AI hype ("revolutionary", "blow your
  mind"). State the pricing edge and the concrete capabilities.
* All claims about pricing and feature coverage match
  `docs/PRICING_STRATEGY.md` and `docs/TOKEN_ECONOMY.md`. If a claim
  is not in the docs, it does not go in the launch copy.
