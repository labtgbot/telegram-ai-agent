# Production использует mock Composio без `COMPOSIO_API_KEY`

Родительский контекст: #206

| Поле | Значение |
| --- | --- |
| Критичность | High |
| Stage | Stage 1 - High priority |
| Labels | `bug`, `backend`, `composio`, `ai-service`, `devops`, `stage-1-high`, `complexity-medium` |
| Status | Confirmed |
| GitHub issue | https://github.com/labtgbot/telegram-ai-agent/issues/208 |

## Кратко

Production-конфигурация может стартовать без `COMPOSIO_API_KEY`. В этом
состоянии backend молча переключает все Composio tool calls на
`MockComposioClient`, который возвращает успешные echo-payloads. Для tests/load
tests это удобно, но как неявный production fallback это опасно.

## Доказательства

- `backend/app/core/config.py:191-194` документирует, что пустой
  `composio_api_key` включает mock client.
- `backend/app/core/config.py:313-315` включает real Composio только когда key
  не пустой.
- `backend/app/core/config.py:347-369` production safety checks требуют
  `ADMIN_JWT_SECRET` и `TELEGRAM_WEBHOOK_SECRET`, но не требуют
  `COMPOSIO_API_KEY`.
- `backend/app/services/composio/client.py:258-279` возвращает
  `MockComposioClient`, если `cfg.composio_enabled` равен false.
- `backend/app/services/composio/mock.py:119-126` возвращает `successful=True`
  с `data={"echo": invocation.params}` для неизвестных tools.
- `deploy/helm/telegram-ai-agent/values.yaml:44-55` содержит
  `COMPOSIO_API_KEY: ""` в secret defaults.
- `deploy/helm/telegram-ai-agent/values-production.yaml:13-23` задает
  production config, но не требует и не валидирует Composio key.

## Влияние

Production deploy может принимать generation requests, резервировать или
списывать user tokens и возвращать mock/echo data вместо вызова real provider.
Сервис выглядит healthy, потому что fallback возвращает successful mock
response; операторы могут заметить проблему только по жалобам пользователей
или расхождению с provider billing.

## Предлагаемое исправление

- Сделать mock Composio mode явным и ограниченным по environment, например
  `COMPOSIO_MODE=mock`, разрешенный только для `development`, `test`, `ci` и
  load tests.
- Добавить fail fast в `Settings.assert_production_safe()`, когда `APP_ENV`
  равен production/staging, real AI generation включен, но `COMPOSIO_API_KEY`
  отсутствует.
- Добавить Helm validation (`values.schema.json` или template `required`) и
  compose env checks, чтобы production manifests не могли рендерить backend с
  неявным mock provider.
- Если Composio намеренно optional, явно отключать generation endpoints и admin
  UI state через disabled-provider status вместо successful mock results.

## Критерии приемки

- [ ] Production/staging startup падает, если real generation включен, а
      `COMPOSIO_API_KEY` пустой.
- [ ] Mock Composio требует явного non-production setting.
- [ ] Helm/compose production paths валидируют key или рендерят понятное
      disabled state.
- [ ] Тесты покрывают production startup без `COMPOSIO_API_KEY` и development
      startup с явным mock mode.
