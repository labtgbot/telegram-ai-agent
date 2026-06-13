# Нет CSRF-защиты на admin auth route handlers

Родительский контекст: #218

| Поле | Значение |
| --- | --- |
| Критичность | Low |
| Stage | Stage 3 - Low priority |
| Labels | `security`, `admin-crm`, `stage-3-low`, `complexity-medium` |
| Status | Confirmed |
| GitHub issue | _pending_ |

## Кратко

Admin auth route handlers (`logout`, `refresh`) не имеют CSRF-защиты. Куки —
`SameSite=lax`, что не блокирует top-level cross-site POST-навигацию. Атакующий
может через cross-site форму инициировать forced-logout или нежелательный
refresh.

## Доказательства

- `admin-dashboard/app/api/auth/logout/route.ts:6-17` — POST без CSRF-токена.
- `admin-dashboard/app/api/auth/refresh/route.ts:7-32` — POST без CSRF-токена.
- `admin-dashboard/lib/auth/cookies.ts:24,31` — `SameSite=lax`.

## Влияние

Forced-logout (DoS-аннойанс) и принудительный refresh через cross-site
top-level POST. Воздействие ограничено (lax частично защищает), отсюда Low.

## Предлагаемое исправление

- Ввести CSRF-токен (double-submit cookie или header-токен) для state-changing
  auth-роутов; либо `SameSite=strict` для auth-кук.

## Критерии приёмки

- [ ] State-changing auth-роуты требуют валидный CSRF-токен.
- [ ] Тест отвергает запрос без токена.
