# Лимит длительности/размера voice audio_url задекларирован, но не проверяется

Родительский контекст: #218

| Поле | Значение |
| --- | --- |
| Критичность | Medium |
| Stage | Stage 2 - Medium priority |
| Labels | `bug`, `ai-service`, `backend`, `stage-2-medium`, `complexity-low` |
| Status | Confirmed |
| GitHub issue | _pending_ |

## Кратко

Сервис обработки голоса декларирует лимиты `MAX_AUDIO_DURATION_SECONDS` и
`MAX_AUDIO_BYTES`, и docstring обещает «validate the audio reference (URL/base64
+ duration cap)». Однако для пути `audio_url` ни размер в байтах, ни длительность
фактически не проверяются — валидируется только base64-путь.

## Доказательства

- `backend/app/services/voice_processing.py:60-61` — заданы
  `MAX_AUDIO_DURATION_SECONDS = 5*60` и `MAX_AUDIO_BYTES = 25 MB`.
- `backend/app/services/voice_processing.py:504-528` — ветка обработки
  `audio_url` не применяет проверки байтов/длительности (в отличие от base64).
- Docstring (строки ~11) заявляет проверку для обоих путей.

## Влияние

Через `audio_url` можно подать произвольно длинный/большой аудио-ресурс в обход
заявленных лимитов: повышенная стоимость обработки/трафика и потенциальный
вектор ресурсного абуза.

## Предлагаемое исправление

- Для `audio_url`: проверять `Content-Length`/`HEAD` против `MAX_AUDIO_BYTES`,
  ограничивать скачиваемый объём, валидировать длительность после загрузки до
  обращения к провайдеру; на превышение — отклонять запрос.
- Привести поведение в соответствие с docstring и base64-путём.

## Критерии приёмки

- [ ] `audio_url` сверх `MAX_AUDIO_BYTES`/`MAX_AUDIO_DURATION_SECONDS`
      отклоняется до вызова провайдера.
- [ ] Тест покрывает превышение лимитов по URL-пути.
