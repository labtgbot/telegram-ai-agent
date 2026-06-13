# Mini-app: AbortController сохраняется, но .abort() не вызывается → streaming fetch не отменяется

Родительский контекст: #218

| Поле | Значение |
| --- | --- |
| Критичность | Low |
| Stage | Stage 3 - Low priority |
| Labels | `bug`, `frontend`, `stage-3-low`, `complexity-low` |
| Status | Confirmed |
| GitHub issue | _pending_ |

## Кратко

В `ChatPage` создаётся и сохраняется `AbortController` для streaming-запроса, но
`.abort()` не вызывается ни при unmount, ни при старте нового запроса. Поток
продолжается в фоне, тратит ресурсы и может вызвать setState после unmount.

## Доказательства

- `mini-app/src/.../ChatPage.tsx:54` — хранение контроллера.
- `mini-app/src/.../ChatPage.tsx:136-137,145,172` — контроллер используется, но
  `.abort()` не вызывается в cleanup/при новом запросе.

## Влияние

Незавершённые streaming-fetch'и при навигации/повторной отправке: лишние
сетевые/CPU-затраты и возможные React-предупреждения о setState после unmount.

## Предлагаемое исправление

- Вызывать `.abort()` в cleanup эффекта и перед стартом нового стрима;
  игнорировать `AbortError`.

## Критерии приёмки

- [ ] При unmount/новом запросе предыдущий стрим отменяется.
- [ ] Нет setState после unmount.
