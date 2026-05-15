# Project Roadmap

## Phases

### Phase 1 (Weeks 1-3): MVP Core
- System Design & Architecture
- Database Schema
- Project Setup (backend, docker, CI)
- Token Management System (базовый)
- Telegram Bot Integration (start, balance, help)
- Composio MCP — базовая интеграция
- Auth & Authorization (бот + админ)

**Goal**: запущен бот, который умеет принимать команды и считать токены в БД.

### Phase 2 (Weeks 4-6): Features
- Payment Processing (Telegram Stars)
- AI services: Image / Video / Text / Web Search / Voice / Documents
- Token consumption per service
- Rate Limiting & Quotas
- Mini App: chat UI, balance, payment flow

**Goal**: полностью рабочий пользовательский продукт.

### Phase 3 (Weeks 7-8): Admin & Polish
- Admin CRM Dashboard (метрики)
- User management UI
- Pricing configuration (dynamic)
- Analytics & Reporting (revenue, retention, LTV)
- Broadcast messaging
- Тесты (unit/integration/E2E)

**Goal**: CRM-инструменты для операционного управления.

### Phase 4 (Weeks 9-10): Production
- Docker / Kubernetes deployment
- Monitoring (Prometheus + Grafana)
- Backup strategy
- Security audit
- Compliance (GDPR, ToS)
- Beta testing + launch

**Goal**: production-ready релиз.

## Issue Decomposition

Все задачи декомпозированы в отдельные GitHub issues с метками:

- `backend`, `frontend`, `admin-crm`, `devops`, `testing`, `security`, `docs`
- `phase-1-mvp`, `phase-2-features`, `phase-3-admin`, `phase-4-production`
- `complexity-low`, `complexity-medium`, `complexity-high`

См. фильтр: <https://github.com/labtgbot/telegram-ai-agent/issues>

## Acceptance Criteria уровня проекта

- Стоимость токенов в среднем на 50% ниже Mira.
- Пользователь может купить токены за Telegram Stars и сразу их потратить.
- Админ может изменить ценообразование без перезапуска сервиса.
- В CRM видны MRR, выручка за день, конверсия и retention.
- Все критические пути покрыты автоматическими тестами.
