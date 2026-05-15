# Deployment (Draft)

Реальный production-runbook будет дополнен в Phase 4. Этот документ задаёт направление.

## Environments

| Env | URL | Database | Notes |
|-----|-----|----------|-------|
| local | localhost | docker postgres | для разработки |
| staging | staging.example.com | managed postgres (small) | для QA / beta |
| production | bot.example.com | managed postgres (HA) | основной трафик |

## Local Development

```bash
git clone https://github.com/labtgbot/telegram-ai-agent
cd telegram-ai-agent
cp .env.example .env       # заполнить токены
docker compose up --build  # backend + postgres + redis + minio
```

Mini App: `cd mini-app && npm install && npm run dev`.
Admin CRM: `cd admin-dashboard && npm install && npm run dev`.

## Telegram Configuration

1. Создать бота через `@BotFather`.
2. Включить payments: `/setpayments` + провайдер Telegram Stars.
3. Webhook: `POST https://<your-domain>/api/v1/bot/webhook` с секретным заголовком.
4. Mini App URL: `/setmenubutton` → `https://<your-domain>/app/`.

## Composio Configuration

1. Зарегистрировать MCP-сервер на https://composio.dev.
2. Получить `COMPOSIO_API_KEY` и список инструментов.
3. Связать с провайдерами Gemini / Claude / GPT.

## CI/CD

- GitHub Actions: lint → test → build → deploy (staging).
- Production deploy — manual approval.
- Тэги релизов: `vMAJOR.MINOR.PATCH`.

## Backups

- Daily snapshot БД + WAL archiving.
- Объектное хранилище (S3) для пользовательских медиа.
- Disaster recovery RPO ≤ 1 час, RTO ≤ 30 минут.

## Monitoring

- Prometheus + Grafana дашборды.
- Sentry для ошибок приложения.
- Алерты: Telegram chat для on-call.

## Security at Deploy

- Все секреты — через secret manager.
- TLS-сертификаты автоматизированы (cert-manager / Caddy).
- Минимальные привилегии для сервис-аккаунтов.
