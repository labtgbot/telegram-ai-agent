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
- Ежедневный бонус: лестница `10 → 12 → 15 → 20` (cap), сбрасывается при
  пропуске UTC-дня. Конфигурируется через CRM (`admin_settings.daily_bonus.amounts`
  или env `DAILY_BONUS_AMOUNTS`). Подробности — раздел «Daily Bonus & Streak» ниже.

## Transactions

Каждое действие пользователя логируется в таблицу `transactions`:

- `purchase` — начисление за оплату
- `spend` — списание за услугу
- `bonus` — бонусы (referral, daily, manual)
- `refund` — возврат

## Source of Truth

`users.token_balance` — материализованный счетчик, обновляется в транзакции вместе с записями в `transactions` и `token_usage_logs`. Для аудита можно пересчитать баланс из транзакций.

## TokenService (Phase 1)

Реализация живёт в `backend/app/services/token_service.py`. Сервис создаётся на каждый запрос с активной `AsyncSession`:

```python
from app.services.token_service import TokenService

service = TokenService(session)
```

Каждый публичный write-метод выполняет операцию атомарно:

1. блокирует строку пользователя через `SELECT ... FOR UPDATE`;
2. обновляет `users.token_balance` и связанные счётчики (`total_tokens_spent`, `total_tokens_purchased`, `total_requests`);
3. дописывает аудит-строки в `transactions` (и `token_usage_logs` для `spend`);
4. делает `flush`, но **не** `commit` — внешняя транзакция управляется вызывающим кодом (паттерн unit-of-work, как в `app.services.bot_users`).

### API

| Метод | Описание | Тип транзакции |
|-------|----------|----------------|
| `await service.add(user_id, amount, transaction_type="bonus", …)` | Начислить токены | `bonus` / `purchase` / `manual_bonus` |
| `await service.spend(user_id, amount, service=…)` | Списать токены, записать в `token_usage_logs` | `spend` |
| `await service.manual_bonus(user_id, amount, reason, admin_id=…)` | Админская корректировка с обязательной причиной | `manual_bonus` |
| `await service.refund(transaction_id, reason=None)` | Возврат — обратная транзакция для `spend` или `purchase` | `refund` |
| `await service.get_balance(user_id)` | Текущий баланс | — |
| `await service.usage_history(user_id, page=1, limit=20)` | Пагинированная история списаний | — |

### Исключения

| Класс | Условие |
|-------|---------|
| `InvalidAmountError` | `amount` не положительное целое (отдельно отвергаются `bool`, `0`, отрицательные, не-`int`, пустой `service`/`reason`, чужой `transaction_type` в `add`) |
| `UserNotFoundError` | Пользователь не найден |
| `InsufficientTokensError(required, available)` | На спенде баланса не хватает; состояние **не** меняется до raise |
| `TransactionNotFoundError` | Refund по несуществующей транзакции |
| `TransactionNotRefundableError` | Refund по транзакции не из `{spend, purchase}` или повторный refund |

`InsufficientTokensError` несёт структурированные поля `required` и `available`, чтобы UI мог показать осмысленный диалог («не хватает X — добавить Y?»).

### Конкурентная безопасность

`_lock_user` берёт row-level lock через `SELECT ... FOR UPDATE`. На PostgreSQL это сериализует параллельные write-операции по одному `user_id` до коммита внешней транзакции — два одновременных `spend` не могут уйти в минус, второй получит `InsufficientTokensError`. Покрыто тестом `test_concurrent_spends_serialise_via_row_lock` (две независимые сессии через `asyncio.gather`).

### Инвариант баланса

Всегда выполняется `users.token_balance == SUM(credit txs) - SUM(spend txs)`, где credit = `{purchase, bonus, manual_bonus, refund}`. Инвариант проверяется в коде сервиса (а не CHECK-constraint в БД), чтобы API мог вернуть структурированную ошибку — см. `docs/DATABASE_SCHEMA.md > Invariants`.

## API Endpoints

Подключены под `/api/v1/user/`, требуют валидный `X-Telegram-Init-Data`:

### `GET /api/v1/user/balance`

```json
{
  "token_balance": 250,
  "is_premium": false,
  "premium_expires_at": null,
  "daily_bonus_available": true
}
```

`daily_bonus_available` — `true`, если пользователь ещё не получал бонус **сегодня (UTC)**. Источник истины — `DailyBonusService.status` (см. раздел «Daily Bonus & Streak»).

### `GET /api/v1/user/usage-history?page=1&limit=20`

```json
{
  "items": [
    {
      "id": 1234,
      "service_type": "image_generation",
      "tokens_consumed": 30,
      "response_status": "ok",
      "processing_time_ms": 4210,
      "request_params": {"style": "hd"},
      "created_at": "2026-05-16T09:14:32Z"
    }
  ],
  "total": 87,
  "page": 1,
  "limit": 20,
  "has_more": true
}
```

`page ∈ [1, 10000]`, `limit ∈ [1, 100]`. Параметры за пределами диапазона дают `422`.

## Reconcile (daily)

Сервис экспортирует две функции для сверки баланса с леджером:

```python
from app.services.token_service import (
    reconcile_user_balance,   # one user → BalanceAudit
    reconcile_all_balances,   # batch → list[BalanceAudit]
)
```

`BalanceAudit(user_id, stored_balance, computed_balance, drift)`; `is_consistent == (drift == 0)`. Drift означает расхождение материализованного `users.token_balance` и пересчёта из `transactions` — алертить надо на любом ненулевом значении.

Запускается раз в сутки через Celery Beat (см. `docs/ARCHITECTURE.md > Workers`). Псевдокод задачи:

```python
@celery_app.task(name="tokens.reconcile_daily")
async def reconcile_daily() -> None:
    async with AsyncSessionLocal() as session:
        audits = await reconcile_all_balances(session)
    drifted = [a for a in audits if not a.is_consistent]
    if drifted:
        logger.error("token.reconcile.drift", count=len(drifted), audits=drifted)
        # alerting hook (Slack / Sentry)
```

Сама регистрация задачи в Beat-расписании добавляется в Phase 2, когда поднимается воркер. Логика проверки уже стабильна и покрыта тестами.

## Daily Bonus & Streak

Реализация — `backend/app/services/daily_bonus.py` (`DailyBonusService`). Сервис строит retention-петлю «зайди ещё раз»: бонус начисляется не чаще одного раза в UTC-сутки, а размер растёт по лестнице, пока пользователь возвращается каждый день.

### Бизнес-правила

- **Окно сброса** — UTC-день (`date.today()` в UTC). Полночь UTC одновременна для всех пользователей и не зависит от часового пояса клиента.
- **Лестница** — кортеж положительных целых, по умолчанию `(10, 12, 15, 20)`; индекс берётся как `min(streak_day - 1, len(amounts) - 1)`, поэтому последний шаг — это «потолок» бонуса.
- **Прогресс стрика**:
  - первый claim → `streak_day = 1`,
  - предыдущий claim был **вчера** (UTC) → `streak_day = prev + 1`,
  - любой другой случай (пропуск ≥ 1 дня) → стрик обнуляется и снова стартует с 1.
- **Master switch** — флаг `daily_bonus.enabled` (admin_settings) или `DAILY_BONUS_ENABLED=false` останавливает выдачу: `claim` бросает `DailyBonusDisabledError`, `status` возвращает `enabled=false, available=false`.

### Источники истины

- **DB** — `daily_bonus_claims` (одна строка на каждый успешный claim). Поле `streak_day` хранит позицию в лестнице, `transaction_id` ссылается на запись в `transactions` (`transaction_type='bonus'`, `package_name='daily_bonus'`).
- **Redis** — горячий кеш по ключу `daily_bonus:user:{id}` (TTL 48ч). Хранит `{claim_date, streak_day}` последнего успешного claim'а. Кеш — best-effort: ошибки чтения/записи логируются и не валят запрос; DB остаётся ground truth при cache miss.
- **transactions** — каждый бонус виден как любое другое начисление; `payment_id = "daily_bonus:user:<id>:date:<YYYY-MM-DD>"` нужен для дедупликации (см. ниже).

### Идемпотентность (три слоя)

| # | Слой | Что ловит |
|---|------|-----------|
| 1 | Service guard | Перед списанием сервис читает последнюю запись (Redis → DB). Если `claim_date == today`, сразу `AlreadyClaimedError`. Покрывает «нажал два раза подряд». |
| 2 | DB UNIQUE | `daily_bonus_claims (user_id, claim_date)` — `IntegrityError` при гонке двух потоков; сервис ловит, откатывает транзакцию и возвращает `AlreadyClaimedError`. |
| 3 | Payment marker | Уникальный частичный индекс по `transactions.payment_id` (миграция `0003_payment_idempotency`) дополнительно блокирует дубль на уровне ledger. |

Все три уровня дают `next_available_at = следующая_полночь UTC`, чтобы клиент мог отрисовать корректный countdown.

### CRM-конфигурация

Без релиза можно поменять:

| Ключ `admin_settings.setting_key` | Тип | Значение |
|-----------------------------------|------|----------|
| `daily_bonus.enabled` | `bool` (или объект `{"enabled": true}`) | Master switch. `false` → `claim` отдаёт `403 daily_bonus_disabled`. |
| `daily_bonus.amounts` | `list[int]` (или объект `{"amounts": [...]}` или CSV `"10,12,15,20"`) | Лестница. Невалидные значения логируются (`daily_bonus.bad_amounts_override`) и заменяются на env-default. |

Соответствующие env-фоллбеки — `DAILY_BONUS_ENABLED`, `DAILY_BONUS_AMOUNTS`. Чтение конфигурации устойчиво к ошибкам: исключение на `admin_settings` логируется и сервис продолжает работу со значениями из `Settings`.

### Поверхности (UI/UX)

- **REST** — `GET /api/v1/user/daily-bonus` (snapshot, безопасно дёргать на каждом ререндере), `POST /api/v1/user/daily-bonus` (атомарное списание + крепко идемпотентно). Полный контракт — `docs/API_REFERENCE.md`.
- **Telegram-бот** — команда `/bonus` и кнопка «🎁 Daily bonus» в `main_menu`. Хэндлер живёт в `backend/app/bot/handlers.py::handle_bonus`, переиспользует `DailyBonusService`.
- **Mini App** — компонент `mini-app/src/components/DailyBonusCard.tsx`, встроен в `HomePage`. Обрабатывает 409 (re-read status) и 403 (показывает «paused»).
