# Root Makefile for the telegram-ai-agent monorepo.
#
# Backend-focused targets shell into ``backend/`` so they work from the repo
# root.  Override BACKEND_DIR if you keep a sibling worktree.

BACKEND_DIR ?= backend
COMPOSE     ?= docker compose -f docker/compose.yml

.PHONY: help install lint format typecheck test test-cov dev \
        compose-up compose-down compose-logs migrate seed clean

help:  ## Показать это сообщение
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

install:  ## Установить backend в editable-режиме с dev extras
	cd $(BACKEND_DIR) && pip install -e ".[dev]"

lint:  ## Проверить код (ruff)
	cd $(BACKEND_DIR) && ruff check .

format:  ## Автоформат (black + ruff --fix)
	cd $(BACKEND_DIR) && ruff check --fix .
	cd $(BACKEND_DIR) && black .

typecheck:  ## Проверить типы (mypy)
	cd $(BACKEND_DIR) && mypy app

test:  ## Прогнать unit-тесты
	cd $(BACKEND_DIR) && pytest

test-cov:  ## Тесты с покрытием
	cd $(BACKEND_DIR) && pytest --cov=app --cov-report=term-missing

dev:  ## Запустить backend локально (uvicorn --reload)
	cd $(BACKEND_DIR) && uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

compose-up:  ## Поднять локальный стек (postgres + redis + backend)
	$(COMPOSE) up -d

compose-down:  ## Остановить локальный стек
	$(COMPOSE) down

compose-logs:  ## Логи всех сервисов стека
	$(COMPOSE) logs -f

migrate:  ## Применить миграции на текущую DATABASE_URL
	cd $(BACKEND_DIR) && alembic upgrade head

seed:  ## Залить dev-данные
	python -m scripts.seed

clean:  ## Удалить кэши и артефакты
	find . -type d -name "__pycache__" -prune -exec rm -rf {} +
	find . -type d -name ".pytest_cache" -prune -exec rm -rf {} +
	find . -type d -name ".mypy_cache" -prune -exec rm -rf {} +
	find . -type d -name ".ruff_cache" -prune -exec rm -rf {} +
