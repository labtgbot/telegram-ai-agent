# Background workers не развернуты и не запланированы в production

Родительский контекст: #206

| Поле | Значение |
| --- | --- |
| Критичность | High |
| Stage | Stage 1 - High priority |
| Labels | `bug`, `backend`, `devops`, `architecture`, `telegram`, `payments`, `analytics`, `stage-1-high`, `complexity-high` |
| Status | Confirmed |
| GitHub issue | https://github.com/labtgbot/telegram-ai-agent/issues/209 |

## Кратко

В коде есть несколько production-critical worker modules, но deployment layer
их не запускает и не планирует. Helm worker deployment указывает на Celery app,
которого нет в backend package, а production/staging values держат worker
disabled.

## Доказательства

- `deploy/helm/telegram-ai-agent/values.yaml:139-147` задает optional worker с
  командой `celery -A app.workers.celery_app worker --loglevel=INFO`.
- `deploy/helm/telegram-ai-agent/values-production.yaml:61-63` оставляет
  `worker.enabled: false` в production.
- `deploy/helm/telegram-ai-agent/templates/worker-deployment.yaml:1-52`
  рендерит worker только при enabled и выполняет command из values.
- `backend/pyproject.toml:10-28` не содержит dependency `celery`.
- `backend/app/workers/` содержит module entrypoints:
  `account_deletion.py`, `broadcast.py`, `daily_analytics.py`,
  `subscriptions.py`, `token_usage_partitions.py` и `video_polling.py`, но
  `app/workers/celery_app.py` отсутствует.
- `deploy/helm/telegram-ai-agent/templates/token-usage-partitions-cronjob.yaml:1-60`
  планирует только token usage partition maintenance; CronJobs или Deployments
  для daily analytics, subscription renewal, account deletion, broadcast
  draining и video polling отсутствуют.
- `docs/PAYMENTS.md:91-99`, `docs/ADMIN_GUIDE.md` и
  `docs/legal/PRIVACY_POLICY.md:130-131` описывают workers как обязательное
  production behavior.

## Влияние

Если включить Helm worker как описано в values/docs, pod упадет из-за
отсутствующего Celery binary/app. Если оставить его disabled, operational
workflows не выполняются: scheduled broadcasts не drain-ятся, subscription
renewals не запускаются по расписанию, account deletion anonymization
пропускает deadline, daily analytics snapshots не обновляются, а video
generation polling опирается только на request-side opportunistic polling.

## Предлагаемое исправление

Выбрать одну production worker architecture и довести ее end to end:

- Option A: добавить явные Kubernetes CronJobs/Deployments и compose services
  для существующих `python -m app.workers.*` entrypoints.
- Option B: реализовать real Celery app, добавить dependency, определить
  queues/beat schedules и перевести workers на Celery.

В обоих вариантах обновить Helm values, production overlays, compose files,
runbooks, monitoring и tests/render checks, чтобы deployment contract совпадал
с worker implementation.

## Критерии приемки

- [ ] Production manifests разворачивают runnable workers или CronJobs для
      broadcast draining, subscription renewal, account deletion, daily analytics и
      video polling.
- [ ] Rendered worker command ссылается на importable module и установленную
      runtime dependency.
- [ ] Production docs описывают фактический scheduling mechanism.
- [ ] CI содержит Helm render/unit check, который ловит missing worker commands
      или missing entrypoints.
