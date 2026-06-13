# Mini-app: URL.createObjectURL превью никогда не revoke → утечка памяти

Родительский контекст: #218

| Поле | Значение |
| --- | --- |
| Критичность | Low |
| Stage | Stage 3 - Low priority |
| Labels | `bug`, `frontend`, `stage-3-low`, `complexity-low` |
| Status | Confirmed |
| GitHub issue | https://github.com/labtgbot/telegram-ai-agent/issues/236 |

## Кратко

Превью вложений создаются через `URL.createObjectURL`, но соответствующий
`URL.revokeObjectURL` нигде не вызывается. Object URL'ы удерживают blob в памяти
до выгрузки документа, что приводит к утечке при многократном выборе файлов.

## Доказательства

- `mini-app/src/.../ChatComposer.tsx:184` — `createObjectURL` без revoke.
- `mini-app/src/.../ChatPage.tsx:417` — аналогично.

## Влияние

Накопление неосвобождённых blob-URL при активной работе с вложениями — рост
потребления памяти, особенно заметный на мобильных устройствах.

## Предлагаемое исправление

- Вызывать `URL.revokeObjectURL` при замене/удалении превью и в cleanup эффекта
  (или на unmount).

## Критерии приёмки

- [ ] Каждый созданный object URL освобождается.
- [ ] Тест/проверка отсутствия накопления URL при повторном выборе файлов.
