# APP_DEBUG=true отдаёт одноразовый admin login code в HTTP-ответе; нет production-guard; .env.example поставляет APP_DEBUG=true

Родительский контекст: #218

| Поле | Значение |
| --- | --- |
| Критичность | High |
| Stage | Stage 1 - High priority |
| Labels | `security`, `backend`, `stage-1-high`, `complexity-low` |
| Status | Confirmed |
| GitHub issue | _pending_ |

## Кратко

Одноразовый код admin-логина должен доставляться вне канала (через бота). Однако
при `APP_DEBUG=true` endpoint возвращает код прямо в теле HTTP-ответа. Флаг
`app_debug` не проверяется в `assert_production_safe()`, а `.env.example`
поставляет `APP_DEBUG=true` по умолчанию — оператор, скопировавший пример в
production, получит утечку второго фактора без какого-либо startup-предупреждения.

## Доказательства

- `backend/app/api/v1/auth.py:204-205` — `_admin_login_exposes_code` возвращает
  `True` при `settings.app_debug or settings.is_development`.
- `backend/app/api/v1/auth.py:214-219` — `code` кладётся в
  `AdminLoginRequestResponse` (`delivery="response"`), когда `expose_code`.
- `backend/app/core/config.py` — `app_debug: bool = Field(default=False)`, но
  `assert_production_safe()` не проверяет `app_debug` (валидируются только
  секреты/Composio).
- `.env.example:14` — `APP_DEBUG=true`.

## Влияние

При случайно унаследованном `APP_DEBUG=true` в production любой, кто может
обратиться к endpoint для известного admin `telegram_id`, получает рабочий
одноразовый login code прямо в ответе, обходя out-of-band доставку. В связке с
оракулом существования админа это резко снижает порог компрометации админки.

## Предлагаемое исправление

- В `assert_production_safe()` запрещать `app_debug=true` (и `delivery=response`)
  при production-окружении — падать на старте.
- В `.env.example` выставить `APP_DEBUG=false`, прокомментировав, что `true`
  допустим только в dev.
- Рассмотреть привязку раскрытия кода исключительно к `is_development`, не к
  `app_debug`.

## Критерии приёмки

- [ ] В production `APP_DEBUG=true` приводит к ошибке старта (или код никогда не
      попадает в ответ).
- [ ] `.env.example` не поставляет небезопасный дефолт.
- [ ] Тест проверяет, что в production-конфиге код не возвращается в ответе.
