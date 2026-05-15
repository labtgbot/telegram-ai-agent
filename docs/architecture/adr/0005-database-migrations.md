# ADR-0005: Миграции БД — Alembic с expand/contract, blue/green-safe

- **Статус**: Accepted
- **Дата**: 2026-05-15
- **Авторы**: @konard
- **Связанные документы**: [issue #3](https://github.com/labtgbot/telegram-ai-agent/issues/3), [DATABASE_SCHEMA.md](../../DATABASE_SCHEMA.md), [deployment.md](../diagrams/deployment.md)

## Контекст

Backend написан на FastAPI + SQLAlchemy 2.0 (async). В продакшне работает 2+ реплики `backend-api` и Celery worker'ы — миграции должны выполняться **без downtime** и **без рассинхрона** между старыми и новыми pod'ами во время раскатки.

Варианты подхода:

- **A**: `SQLAlchemy create_all` или ручной SQL — не годится для продакшна.
- **B**: Alembic + наивные миграции (drop/rename в одной транзакции, отдельный pre-deploy step).
- **C**: Alembic + expand/contract (zero-downtime schema migrations) + автоматический запуск в Helm hook.

## Рассмотренные варианты

### A. SQLAlchemy auto / ручной SQL
- Минусы: нет версионирования, нельзя откатиться, легко разъехаться с моделью.

### B. Alembic «как есть»
- Плюсы: стандарт сообщества, версионирование, autogenerate.
- Минусы: drop column / rename column ломает старые pod'ы во время rolling update. На MVP допустимо, но не для продакшна.

### C. Alembic + expand/contract
- Плюсы:
  - Schema change → совместима со старой и новой версией кода → можно деплоить без даунтайма.
  - Стандартная практика для blue/green и rolling deploy.
- Минусы:
  - Каждое разрушительное изменение делится на 2–3 PR (expand → migrate data → contract).
  - Требует дисциплины ревью.

## Решение

Принят **Вариант C**. Все изменения схемы — через Alembic с правилом expand/contract.

### Инструмент

- **Alembic** (последняя версия совместимая с SQLAlchemy 2.0 async).
- Файлы миграций — `backend/alembic/versions/`.
- Конфиг — `backend/alembic.ini`, URL из переменной окружения `DATABASE_URL`.
- `script.py.mako` шаблон требует ручного описания миграции (autogenerate используется как подсказка, не как источник истины).

### Правила expand/contract

Любое **обратно-несовместимое** изменение схемы выполняется в три шага, **каждый — отдельный merge в main**:

1. **Expand** — добавить новое (NULL-able column / новая таблица / новый индекс concurrently). Старый код работает, новый — тоже.
2. **Migrate** — данные переносятся в фоне (Alembic data migration или Celery-задача). Оба пути чтения/записи работают.
3. **Contract** — удалить старое (drop column / drop table). Только после раскатки нового кода во всех репликах.

Конкретные правила:

| Действие | Безопасно | Шаги |
|----------|-----------|------|
| `ADD COLUMN NULL` | да | 1 миграция |
| `ADD COLUMN NOT NULL DEFAULT …` | в Postgres 11+ безопасно (метадата), но осторожно с большими таблицами | 1 миграция, замерить блокировку |
| `RENAME COLUMN` | **нет** | expand: новая колонка → синхронизация (триггер или код) → contract: удалить старую |
| `DROP COLUMN` | **нет** | сначала перестать использовать в коде (релиз) → contract |
| `ADD INDEX` | **CONCURRENTLY обязательно** | `op.create_index(..., postgresql_concurrently=True)` + `with op.get_context().autocommit_block():` |
| `ALTER COLUMN TYPE` (lossy) | **нет** | expand: новая колонка → миграция данных → contract |
| `ADD CONSTRAINT NOT VALID` → `VALIDATE CONSTRAINT` | да | даёт zero-downtime check constraint |
| `DROP TABLE` | **нет** в один шаг | сначала перестать использовать в коде (релиз) → contract |

### Запуск миграций

- В Kubernetes: pre-install/pre-upgrade `Helm hook` с Job, который запускает `alembic upgrade head`.
- Не запускаем миграции из обычного pod'а (race condition между репликами).
- В dev: `make migrate` или `docker compose run backend alembic upgrade head`.

### Откат

- Все миграции содержат рабочий `downgrade()`.
- Откат данных, потерянных при `DROP`, — невозможен; поэтому contract-шаг — только после backup.
- Перед каждым contract-шагом — снимок БД (PITR уже есть).

### Partitioning

`token_usage_logs` партиционирован по `created_at` (см. [DATABASE_SCHEMA.md](../../DATABASE_SCHEMA.md)). Создание новых партиций — отдельная ежемесячная миграция (или Celery beat job).

### Blue/Green vs Rolling

- На MVP используем **rolling update**: достаточно при expand/contract.
- Blue/green как альтернатива остаётся возможной (Argo Rollouts), но не требуется по умолчанию — это лишняя инфраструктура для MVP.

## Последствия

**Положительные**
- Нулевой downtime при изменениях схемы.
- Дисциплина review: рецензент проверяет «совместима ли миграция со старой версией кода».
- Откаты возможны для большинства миграций.

**Отрицательные / компромиссы**
- Каждое разрушительное изменение требует 2–3 релизов вместо одного.
- Удлиняется time-to-cleanup технического долга — но это сознательный компромисс ради SLA.

**Документация / процессы**
- В шаблоне PR добавляем чек-лист «expand/contract проверен» — будет в задаче `[Phase 1] Project Setup / CI`.
- В CONTRIBUTING описать процедуру создания миграции.

**Out of scope**
- Online-rewrite таблиц через `pg_repack` / `pg_squeeze` — потребуется только при >100 GB таблицах.

## Метрики успеха

- 0 деплоев с downtime из-за миграций.
- 100% миграций имеют рабочий `downgrade()` (проверяется в CI: `alembic downgrade -1 && alembic upgrade head`).
- Lock-time на DDL ≤ 1 сек p95 (мониторим `pg_locks`).
- В CI миграции прогоняются на свежей БД и на копии prod-схемы.
