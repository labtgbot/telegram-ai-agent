# Contributing

Спасибо за интерес к проекту **Telegram AI Agent**.

## Workflow

1. Возьмите задачу из [Issues](https://github.com/labtgbot/telegram-ai-agent/issues). Если задача отсутствует — создайте новую и обсудите её.
2. Создайте ветку от `main`: `git checkout -b feature/<short-name>` или `fix/<short-name>`.
3. Сделайте изменения, добавьте тесты, проверьте локально (`make lint`, `make test`).
4. Откройте Pull Request с заполненным шаблоном.
5. Дождитесь зелёного CI и review. Минимум 1 approve от мейнтейнера.

## Branch Naming

- `feature/<scope>` — новая функциональность
- `fix/<scope>` — исправление бага
- `chore/<scope>` — рутинные задачи
- `docs/<scope>` — только документация
- `refactor/<scope>` — рефакторинг без изменений поведения

## Commit Style

Используем [Conventional Commits](https://www.conventionalcommits.org/):

```
feat(tokens): add daily bonus accrual
fix(payments): handle duplicate webhook for invoice
docs(readme): add architecture overview
```

Структура:
- `feat:` новое поведение
- `fix:` исправление бага
- `docs:` документация
- `chore:` build, инфра, зависимости
- `refactor:` без изменения поведения
- `test:` только тесты

## Code Style

- **Python**: `ruff`, `black`, `mypy`. Минимальное покрытие тестами — 70%.
- **TypeScript / React**: `eslint`, `prettier`, `typescript --strict`.
- Все публичные API документируются (docstrings / JSDoc).

## Pull Request Checklist

- [ ] Заголовок в формате Conventional Commits.
- [ ] Описание ссылается на issue (`Fixes #N`).
- [ ] Добавлены/обновлены тесты.
- [ ] Обновлена документация при изменении поведения.
- [ ] Локальные проверки (`make lint`, `make test`) проходят.
- [ ] CI зелёный.

## Local Setup

См. `docs/DEPLOYMENT.md` (будет добавлен в Phase 1).

## Code of Conduct

Уважительное отношение, аргументированные ревью, без личных обсуждений и токсичности.
