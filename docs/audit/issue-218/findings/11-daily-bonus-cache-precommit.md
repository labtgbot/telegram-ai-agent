# Daily-bonus: streak-кэш пишется после flush, но до внешнего commit → ложный AlreadyClaimed и рассинхрон streak

Родительский контекст: #218

| Поле | Значение |
| --- | --- |
| Критичность | Medium |
| Stage | Stage 2 - Medium priority |
| Labels | `bug`, `tokens`, `backend`, `stage-2-medium`, `complexity-medium` |
| Status | Confirmed |
| GitHub issue | https://github.com/labtgbot/telegram-ai-agent/issues/230 |

## Кратко

`DailyBonusService.claim` пишет «последнее начисление» в Redis-кэш сразу после
`session.flush()`, но до внешнего `commit()` (commit выполняет вызывающий код,
например webhook-handler). Если внешний commit затем падает и делается rollback,
запись в БД не сохраняется, а кэш уже содержит `claim_date=today`. Последующие
`status()/claim()` читают кэш и выдают ложный `AlreadyClaimed`, а streak
рассинхронизируется с БД.

## Доказательства

- `backend/app/services/daily_bonus.py:365-378` — после `flush()` сразу
  `_write_latest_to_cache(...)`; commit здесь не делается.
- `backend/app/services/daily_bonus.py:319-324` — guard читает кэш первым и при
  `claim_date == today` бросает `AlreadyClaimedError`.
- `backend/app/services/daily_bonus.py:270-274` — docstring утверждает, что кэш
  пишется «после успешного claim», но «успех» здесь — flush, а не commit.
- `backend/app/api/v1/bot.py:153-160` — внешний commit выполняется позже и может
  упасть с rollback.

## Влияние

При транзиентном сбое внешнего commit пользователь не получает бонус (БД
откатилась), но кэш помечает день как «получено» → пользователь лишается бонуса
за день и не может повторить до истечения TTL/полуночи; streak в кэше расходится
с БД.

## Предлагаемое исправление

- Писать кэш только после успешного внешнего commit (post-commit hook/событие
  SQLAlchemy) либо инвалидация кэша при rollback.
- Альтернатива: кэшировать только подтверждённое состояние из БД, не «прогнозно».

## Критерии приёмки

- [ ] Откат внешней транзакции не оставляет в кэше фантомный claim.
- [ ] После rollback пользователь может повторно запросить бонус.
- [ ] Тест: сбой commit после `claim()` → кэш не блокирует повтор.
