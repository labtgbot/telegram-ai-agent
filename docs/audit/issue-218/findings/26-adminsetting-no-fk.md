# AdminSetting.updated_by хранит user id без FK на users.id

Родительский контекст: #218

| Поле | Значение |
| --- | --- |
| Критичность | Low |
| Stage | Stage 3 - Low priority |
| Labels | `database`, `backend`, `stage-3-low`, `complexity-low` |
| Status | Confirmed |
| GitHub issue | https://github.com/labtgbot/telegram-ai-agent/issues/245 |

## Кратко

Столбец `AdminSetting.updated_by` хранит идентификатор пользователя, но не имеет
FK на `users.id` (в отличие от других admin-content таблиц). Это допускает
orphaned-ссылки; GDPR-анонимизация при удалении пользователя не очищает это поле.

## Доказательства

- `backend/app/models/admin_setting.py:19` — `updated_by` без `ForeignKey`.
- `backend/alembic/versions/20260515_0001_baseline_initial_schema.py:202` —
  миграция создаёт столбец без FK-constraint.

## Влияние

Ссылочная целостность не гарантируется; после удаления пользователя
`updated_by` может указывать на несуществующего юзера, оставляя след в обход
GDPR-анонимизации.

## Предлагаемое исправление

- Добавить FK `updated_by → users.id` (с `ON DELETE SET NULL`) или включить
  столбец в GDPR-анонимизацию; миграция + откат.

## Критерии приёмки

- [ ] `updated_by` имеет ссылочную целостность либо очищается при удалении
      пользователя.
- [ ] Миграция и тест покрывают поведение.
