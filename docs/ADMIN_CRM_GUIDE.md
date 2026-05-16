# Admin CRM Guide (Draft)

CRM-панель построена на Next.js 14 и взаимодействует с Backend через `/api/v1/admin/*` endpoints.

## Modules

### Dashboard
- KPI карточки: users total / new / active, revenue today / MRR, tokens sold, conversion rate.
- Графики: revenue 30d, активность 7d.
- Последние транзакции, последние новые пользователи.

### Users
- Таблица с поиском, фильтрами (premium, banned), сортировкой.
- Карточка пользователя: история транзакций, использование сервисов, рефералы.
- Действия: начислить токены, выдать премиум, забанить/разбанить, отправить сообщение.
- Экспорт CSV.

### Transactions
- Таблица с фильтром по типу, статусу, дате.
- Детали транзакции, повтор обработки webhook, возврат.

### Pricing
- Текущие пакеты с возможностью редактировать stars / tokens / discount.
- Глобальная скидка (применяется ко всем пакетам).
- Сезонные промо.
- Изменения применяются мгновенно.

### Analytics
- Воронка конверсии.
- Retention day 1 / 7 / 30.
- LTV, средний чек, повторные покупки.
- Расход токенов по сервисам.

### Broadcast
- Создание рассылки: текст, медиа, целевая аудитория (all / premium / free / segments).
- Расписание отправки, дельта между сообщениями для соблюдения лимитов Telegram.

### Settings
- Maintenance mode.
- Rate limits.
- Composio config: включенные тулы.
- Логи действий админов (immutable).

### Daily Bonus (`admin_settings`)
Управляется без релиза через таблицу `admin_settings`:

| `setting_key` | Тип | Назначение |
|---------------|------|------------|
| `daily_bonus.enabled` | `bool` или `{"enabled": true}` | Master switch. `false` → пользователь получает `403 daily_bonus_disabled` и видит «paused» в Mini App / боте. |
| `daily_bonus.amounts` | `list[int]` / `{"amounts": [...]}` / CSV `"10,12,15,20"` | Лестница стрика; последний элемент — потолок. Невалидное значение игнорируется (в логах `daily_bonus.bad_amounts_override`), сервис продолжает работу с env-default. |

Изменения применяются мгновенно — сервис читает конфиг при каждом claim'е. Подробности — `docs/TOKEN_ECONOMY.md > Daily Bonus & Streak`.

## Roles

- `super_admin` — всё, включая ценообразование и системные настройки.
- `support_admin` — пользователи, транзакции, ручные бонусы.
- `analyst` — только просмотр аналитики.

## Audit Log

Каждое действие админа пишется в `admin_audit_logs` (создаётся в Phase 3): action, actor, target, before/after, IP, user agent.
