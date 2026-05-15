# Token Economy

## Packages

| Package | Tokens | Stars | Mira Equiv | Discount |
|---------|--------|-------|------------|----------|
| Starter | 500 | 250 ⭐ | 500 ⭐ | -50% |
| Basic | 1,200 | 500 ⭐ | 1,000 ⭐ | -50% |
| Premium | 2,000 | 750 ⭐ | 1,500 ⭐ | -50% |
| Pro (subscription) | 2,000 / month | 500 ⭐ / month | 999 ⭐ | -50% |

> Цены управляются через CRM и могут меняться без релиза (`admin_settings` таблица).

## Consumption Rates

```python
TOKEN_CONSUMPTION = {
    "image_generation": {"standard": 30, "hd": 50, "ultra_hd": 100},
    "video_generation": {"short_5s": 100, "medium_15s": 250, "long_60s": 800},
    "text_query": {"basic_ai": 1, "advanced_ai": 5, "autonomous_agent": 10},
    "voice_message": 5,
    "document_analysis": 20,
    "web_search": 3,
}
```

## Bonuses

- Регистрация: +50 токенов.
- Первая покупка: +20% к токенам.
- Реферал: +100 токенов за каждого приглашенного.
- Ежедневный бонус: +10 токенов при заходе в бота.

## Transactions

Каждое действие пользователя логируется в таблицу `transactions`:

- `purchase` — начисление за оплату
- `spend` — списание за услугу
- `bonus` — бонусы (referral, daily, manual)
- `refund` — возврат

## Source of Truth

`users.token_balance` — материализованный счетчик, обновляется в транзакции вместе с записями в `transactions` и `token_usage_logs`. Для аудита можно пересчитать баланс из транзакций.
