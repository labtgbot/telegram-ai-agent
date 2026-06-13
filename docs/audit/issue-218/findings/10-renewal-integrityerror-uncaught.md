# Subscription renewal worker ловит только UserNotFoundError, но не IntegrityError на дублирующем renewal-marker

Родительский контекст: #218

| Поле | Значение |
| --- | --- |
| Критичность | Medium |
| Stage | Stage 2 - Medium priority |
| Labels | `bug`, `payments`, `backend`, `stage-2-medium`, `complexity-medium` |
| Status | Confirmed |
| GitHub issue | https://github.com/labtgbot/telegram-ai-agent/issues/229 |

## Кратко

`process_subscription_renewals` вычисляет `period_index` подсчётом существующих
продлений и формирует `renewal:{sub_id}:{period_index}` как `payment_id`.
Проверка «маркер уже существует» неатомарна, а вставка через
`TokenService.add()` защищена partial-unique индексом по `payment_id`. При
конкурентных прогонах (нет row-claiming на выборке due-подписок) второй worker
получает `IntegrityError`, который НЕ перехватывается (ловится только
`UserNotFoundError`) → исключение всплывает и роняет общий батч в одной сессии,
оставляя оставшиеся подписки непродлёнными.

## Доказательства

- `backend/app/services/payments.py:830-847` — выборка due-подписок без
  `with_for_update()`/claiming.
- `backend/app/services/payments.py:860-870` — неатомарная проверка
  существования `renewal_marker`.
- `backend/app/services/payments.py:872-887` — вставка через `token_service.add`.
- `backend/app/services/payments.py:888-897` — `except UserNotFoundError`, но не
  `IntegrityError`.
- `backend/app/models/transaction.py:69-72` — partial-unique индекс
  `uq_transactions_payment_id`.

## Влияние

Перекрытие двух прогонов renewal-воркера приводит к необработанному
`IntegrityError`, который прерывает цикл и оставляет часть подписок без
продления (аналогично «один сбой роняет батч»). Для пользователей — пропуск
автопродления.

## Предлагаемое исправление

- Перехватывать `IntegrityError` на вставке renewal: rollback savepoint и
  трактовать как «уже продлено» (advance expiry, continue) по аналогии с
  обработкой дубля в `finalize_successful_payment`.
- Добавить row-claiming/`with_for_update(skip_locked=True)` на выборке due-
  подписок, чтобы исключить параллельную обработку одной подписки.

## Критерии приёмки

- [ ] Конкурентные прогоны не роняют батч; дубль renewal обрабатывается
      идемпотентно.
- [ ] Одна подписка не продлевается дважды.
- [ ] Тест воспроизводит дубль renewal-marker и проверяет корректную обработку.
