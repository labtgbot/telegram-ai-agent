# Mini-app HistoryPage: гонка stale-response в fetch-эффекте

Родительский контекст: #218

| Поле | Значение |
| --- | --- |
| Критичность | Medium |
| Stage | Stage 2 - Medium priority |
| Labels | `bug`, `frontend`, `stage-2-medium`, `complexity-low` |
| Status | Confirmed |
| GitHub issue | https://github.com/labtgbot/telegram-ai-agent/issues/228 |

## Кратко

`HistoryPage` запускает асинхронный fetch в эффекте без abort/ignore-guard. При
быстрой смене параметров (фильтр/страница) или unmount раньше стартовавший
запрос может завершиться позже и перезаписать состояние более свежим/неактуальным
ответом, а также вызвать setState после unmount.

## Доказательства

- `mini-app/src/.../HistoryPage.tsx:69-89` — fetch-эффект без `AbortController`
  и без флага `ignore`/cleanup; результат пишется в state безусловно.

## Влияние

Отображение устаревших данных истории, мерцание/перетирание актуального ответа,
предупреждения React о setState после unmount.

## Предлагаемое исправление

- Добавить `let ignore = false` (или `AbortController`) в эффект и
  игнорировать/отменять устаревший ответ в cleanup.
- Привязать инвалидцию к ключу запроса (фильтр/страница).

## Критерии приёмки

- [ ] Быстрая смена параметров не приводит к перетиранию свежего результата
      устаревшим.
- [ ] Нет setState после unmount.
- [ ] Тест воспроизводит гонку и проверяет игнор устаревшего ответа.
