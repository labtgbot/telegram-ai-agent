# SSE start-event: расхождение поля request_id (backend) vs requestId (frontend)

Родительский контекст: #218

| Поле | Значение |
| --- | --- |
| Критичность | Low |
| Stage | Stage 3 - Low priority |
| Labels | `bug`, `frontend`, `backend`, `stage-3-low`, `complexity-low` |
| Status | Confirmed |
| GitHub issue | _pending_ |

## Кратко

Backend в start-событии SSE отдаёт поле `request_id` (snake_case), а frontend
читает `requestId` (camelCase). Значение на клиенте оказывается `undefined`;
существующий тест закрепляет неверный контракт, маскируя дефект.

## Доказательства

- `backend/app/api/v1/generate.py:979` — событие содержит `request_id`.
- `mini-app/src/.../chatApi.ts:26-27,142` — клиент ожидает `requestId`.
- `mini-app/src/.../chatApi.test.ts:31,100` — тест использует `requestId`,
  фиксируя неверный контракт.

## Влияние

`requestId` на клиенте всегда `undefined` — теряется корреляция запроса (отмена,
логирование, привязка ответов). Скрытый контрактный баг.

## Предлагаемое исправление

- Согласовать имя поля по обе стороны (выбрать единый стиль), исправить тест на
  корректный контракт.

## Критерии приёмки

- [ ] Клиент получает непустой идентификатор запроса из start-события.
- [ ] Тест проверяет фактический backend-контракт.
