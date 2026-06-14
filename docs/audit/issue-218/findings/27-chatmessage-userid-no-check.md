# ChatMessage.user_id денормализован от thread.user_id без CHECK/guard

Родительский контекст: #218

| Поле | Значение |
| --- | --- |
| Критичность | Low |
| Stage | Stage 3 - Low priority |
| Labels | `database`, `backend`, `stage-3-low`, `complexity-low` |
| Status | Confirmed |
| GitHub issue | https://github.com/labtgbot/telegram-ai-agent/issues/246 |

## Кратко

`ChatMessage` хранит и `thread_id` (FK), и денормализованный `user_id` (FK), но
нет гарантии (CHECK/триггер/инвариант), что `chat_messages.user_id` совпадает с
`chat_threads.user_id`. Data-export читает `ChatMessage.user_id` напрямую,
полагаясь на синхронность.

## Доказательства

- `backend/app/models/chat_history.py:100-110` — оба FK без consistency-guard.
- `backend/alembic/versions/20260516_0005_chat_history.py:149-152` — CHECK есть
  только для `role`, не для согласованности `user_id`.
- `backend/app/services/data_export.py:232` — экспорт фильтрует по
  `ChatMessage.user_id` напрямую.

## Влияние

При баге/гонке записи сообщение может быть атрибутировано не тому пользователю; в
GDPR-экспорт попадут/не попадут чужие сообщения. Сейчас риск низкий (значения
выставляются в коде), но БД-гарантии нет.

## Предлагаемое исправление

- Либо убрать денормализацию и джойнить через `thread_id`, либо добавить
  гарантию согласованности (триггер/проверка на уровне приложения с тестом).

## Критерии приёмки

- [ ] `user_id` сообщения согласован с владельцем треда (гарантия или тест).
- [ ] Экспорт не атрибутирует сообщения чужому пользователю.
