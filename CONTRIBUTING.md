# Contributing

Спасибо за интерес к проекту **Telegram AI Agent** — Telegram-бот с
токеновой экономикой, Mini App и CRM-панелью. Этот документ описывает,
как присоединиться к разработке и провести изменения через ревью.

- Архитектура: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)
- API: [`docs/API_REFERENCE.md`](docs/API_REFERENCE.md) (+ live OpenAPI
  на `/docs`)
- Deployment: [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md)
- Roadmap: [`docs/ROADMAP.md`](docs/ROADMAP.md)
- Security policy: [`SECURITY.md`](SECURITY.md)

---

## 1. Workflow

1. Возьмите задачу из
   [Issues](https://github.com/labtgbot/telegram-ai-agent/issues). Если
   подходящей задачи нет — создайте новую и обсудите её прежде, чем
   писать код.
2. Создайте ветку от `main`: `git checkout -b feature/<short-name>`,
   `fix/<short-name>`, `docs/<short-name>` и т.п.
3. Сделайте изменения, добавьте/обновите тесты, прогоните локальные
   проверки (`make lint`, `make typecheck`, `make test`).
4. Откройте Pull Request с заполненным шаблоном; сошлитесь на issue
   (`Fixes #N`).
5. Дождитесь зелёного CI и review. Для merge нужен минимум **1
   approve** от мейнтейнера; security-чувствительные изменения требуют
   2 approve (включая `@labtgbot/security`).
6. Squash-merge или rebase-merge по решению мейнтейнера; история на
   `main` остаётся линейной.

> Ветка `main` защищена: прямой push запрещён, force-push запрещён,
> требуются зелёный CI и review.

---

## 2. Local setup

### 2.1 Requirements

- Python 3.11+ (`pyenv install 3.11` рекомендован).
- Node.js 20+ (используется и в `mini-app/`, и в `admin-dashboard/`).
- Docker + Docker Compose (для локальной БД, Redis и интеграционных
  тестов).
- `make` (Linux/macOS) или WSL2 на Windows.

### 2.2 Quick start (backend)

```bash
make install               # editable install + dev extras
cp .env.example .env       # заполните минимальные переменные
make compose-up            # postgres + redis в Docker
make migrate               # применить миграции
make dev                   # uvicorn на http://localhost:8000
```

Полезные ярлыки:

| Команда         | Что делает                                             |
|-----------------|--------------------------------------------------------|
| `make lint`     | `ruff check .`                                         |
| `make format`   | `ruff --fix` + `black`                                 |
| `make typecheck`| `mypy app`                                             |
| `make test`     | `pytest`                                               |
| `make test-cov` | `pytest --cov=app --cov-report=term-missing`           |
| `make seed`     | Залить dev-данные                                      |

### 2.3 Frontend (Mini App / Admin)

```bash
cd mini-app && npm ci && npm run dev          # http://localhost:5173
cd admin-dashboard && npm ci && npm run dev   # http://localhost:3000
```

Pre-commit хуки и lint-staged конфигурируются на стороне каждого
суб-проекта; запустите `npm run lint` и `npm run typecheck` перед PR.

---

## 3. Branch naming

| Префикс           | Когда использовать                              |
|-------------------|--------------------------------------------------|
| `feature/<scope>` | новая функциональность                           |
| `fix/<scope>`     | исправление бага                                 |
| `docs/<scope>`    | только документация                              |
| `chore/<scope>`   | инфраструктура, зависимости, мелкая рутина       |
| `refactor/<scope>`| рефакторинг без изменения поведения              |
| `test/<scope>`    | только тесты                                     |
| `perf/<scope>`    | оптимизации производительности                   |
| `security/<scope>`| security-fix (приоритет, отдельная процедура)    |

---

## 4. Commit style — Conventional Commits

Используем [Conventional Commits](https://www.conventionalcommits.org/):

```
feat(tokens): add daily bonus accrual
fix(payments): handle duplicate webhook for invoice
docs(api): document daily-bonus endpoints
refactor(auth): extract TOTP service
chore(deps): bump fastapi to 0.111
```

Структура: `<type>(<scope>): <subject>`. Хорошее `<subject>` —
повелительное наклонение, < 72 символов, без точки в конце.

Когда уместно — расширьте сообщение телом коммита, объясняя **почему**
(контекст), а не **что** (виден в diff).

---

## 5. Code style

### 5.1 Python

- `ruff` (E, F, I, B, UP, N, SIM) + `black` (line-length 100).
- `mypy` на каталоге `app/`. Strict-mode выключен глобально, но
  публичные сигнатуры аннотируются.
- Минимальное покрытие тестами для нового кода — **70%**.
- Логирование — структурированный `structlog`; никакой PII в логах
  (см. `app/core/logging.py > scrub_pii`).

### 5.2 TypeScript / React

- `eslint`, `prettier`, `typescript --strict`.
- Состояние — компоненты + React Query (избегаем избыточного Redux).
- Компоненты — функциональные, hooks-style; storybook-сниппеты в
  `mini-app/src/components/__stories__/`.
- Доступность — все интерактивные элементы фокусируются и имеют
  `aria-*` атрибуты.

### 5.3 Документация

- Все публичные API документируются (docstrings / JSDoc / OpenAPI
  schemas).
- Новые архитектурные решения фиксируйте как ADR в
  `docs/architecture/adr/`.
- Изменения в публичных API синхронизируются с
  `docs/API_REFERENCE.md` (или явно отмечаются как breaking).

---

## 6. Testing

| Уровень           | Каталог / команда                                     |
|-------------------|-------------------------------------------------------|
| Backend unit      | `backend/tests/test_*.py` → `make test`               |
| Backend integ     | `backend/tests/integration/` → `pytest -m integration`|
| Mini-app unit     | `mini-app/tests/` → `npm test`                        |
| Mini-app e2e      | `mini-app/tests/e2e/` → `npm run test:e2e`            |
| Admin unit/e2e    | `admin-dashboard/tests/` → `npm test`, `npm run e2e`  |
| Load              | `loadtest/*.js` (k6)                                  |

Новые баги фиксируйте регрессионным тестом **до** фикса. UI-баги — со
скриншотами before/after в PR.

---

## 7. Pull request checklist

- [ ] Заголовок в формате Conventional Commits.
- [ ] Описание ссылается на issue (`Fixes #N`) и кратко объясняет
      зачем меняем.
- [ ] Добавлены/обновлены тесты.
- [ ] Обновлена документация (`docs/`, README, OpenAPI), если меняется
      поведение.
- [ ] Локально прошли `make lint`, `make typecheck`, `make test`
      (плюс `npm run …` для затронутых JS-проектов).
- [ ] CI зелёный.
- [ ] Для UI-изменений — приложены before/after скриншоты или
      записи экрана.
- [ ] Для security-чувствительных изменений — отметка `@labtgbot/security`
      в ревьюерах.

---

## 8. Security & responsible disclosure

Подозрение на уязвимость **не** заводится публичным issue. Следуйте
процедуре в [`SECURITY.md`](SECURITY.md). Краткая выжимка: пишите
на `security@example.com`, дайте 90 дней до публичного раскрытия.

---

## 9. Code of Conduct

Уважительное отношение, аргументированные ревью, без личных переходов
и токсичности. Несогласие — нормально; обоснованный код — лучший
аргумент. Если конфликт не разрешается — поднимайте к мейнтейнеру.
