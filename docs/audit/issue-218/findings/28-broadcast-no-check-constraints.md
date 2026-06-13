# Broadcast.status/audience и BroadcastRecipient.status без CHECK-constraints

Родительский контекст: #218

| Поле | Значение |
| --- | --- |
| Критичность | Low |
| Stage | Stage 3 - Low priority |
| Labels | `database`, `backend`, `stage-3-low`, `complexity-low` |
| Status | Confirmed |
| GitHub issue | _pending_ |

## Кратко

Модель broadcast определяет справочники допустимых значений
(`BROADCAST_STATUSES`, `BROADCAST_AUDIENCES`, `RECIPIENT_STATUSES`), но столбцы
`Broadcast.status`/`audience` и `BroadcastRecipient.status` не имеют CHECK-
constraints — в отличие от `VideoJob`/`Transaction`/`AccountDeletionRequest`.
Defence-in-depth непоследователен.

## Доказательства

- `backend/app/models/broadcast.py:42-70,78-84` — справочники значений.
- `backend/app/models/broadcast.py:107-109,135-140,165-167` — столбцы без
  CHECK в `__table_args__`.
- `backend/alembic/versions/20260516_0008_broadcasts.py` — миграция без CHECK.

## Влияние

Прямые SQL-вставки могут записать недопустимый status/audience в обход
приложения. Низкий риск (валидация в сервисном слое), но нарушает применяемый в
остальной схеме принцип.

## Предлагаемое исправление

- Добавить `CheckConstraint` для статусов/аудитории по справочникам; миграция +
  откат.

## Критерии приёмки

- [ ] Недопустимые значения отвергаются на уровне БД.
- [ ] Миграция и тест покрывают ограничение.
