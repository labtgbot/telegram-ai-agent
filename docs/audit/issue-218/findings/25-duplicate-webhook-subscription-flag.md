# Дублирующий payment webhook возвращает is_subscription=is_recurring вместо package.is_subscription

Родительский контекст: #218

| Поле | Значение |
| --- | --- |
| Критичность | Low |
| Stage | Stage 3 - Low priority |
| Labels | `bug`, `payments`, `backend`, `stage-3-low`, `complexity-low` |
| Status | Confirmed |
| GitHub issue | _pending_ |

## Кратко

При обработке дублирующего payment-webhook (ранний возврат и ветка
`IntegrityError`-гонки) `PaymentResult.is_subscription` заполняется значением
`is_recurring` (флаг автопродления Telegram), а не `package.is_subscription`
(является ли пакет подпиской). Это разные понятия; на дубликате premium-UX может
отображаться неверно.

## Доказательства

- `backend/app/services/payments.py:407` — ранний дубль: `is_subscription=is_recurring`.
- `backend/app/services/payments.py:472` — ветка IntegrityError: то же.
- `backend/app/services/payments.py:506` — корректный путь использует
  `package.is_subscription`.

## Влияние

На redelivery/дубле пользователь может увидеть некорректную информацию о статусе
премиума/подписки. Чисто отображательный дефект, отсюда Low.

## Предлагаемое исправление

- В дубль-ветках возвращать `package.is_subscription` (распарсив пакет там, где
  он ещё не доступен) для согласованности с основным путём.

## Критерии приёмки

- [ ] Дубль-вебхук отдаёт тот же `is_subscription`, что и исходная обработка.
- [ ] Тест сверяет флаг на первичной и повторной доставке.
